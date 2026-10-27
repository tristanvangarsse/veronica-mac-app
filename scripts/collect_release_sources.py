#!/usr/bin/env python3
"""Collect checksum-verified upstream sources matching a packaged runtime."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def collect(engine, output, cache):
    internal=Path(engine).resolve().parent/'_internal';output=Path(output).resolve();cache=Path(cache).resolve()
    output.mkdir(parents=True,exist_ok=True);cache.mkdir(parents=True,exist_ok=True)
    metadata=output/'build-recipes';metadata.mkdir(exist_ok=True)
    media=json.loads((internal/'MediaTools/manifest.json').read_text());requests=[]
    def add(name,url,checksum=None):
        if '#{' in url:raise ValueError('Unresolved source URL: '+url)
        if not url.startswith('https://'):raise ValueError('Only HTTPS source archives are accepted')
        requests.append({'name':name,'url':url,'sha256':checksum})
    for package,keg in sorted(media['packages'].items()):
        keg=Path(keg);formula=next((keg/'.brew').glob('*.rb'));text=formula.read_text()
        version=re.search(r'^  version "([^"]+)"',text,re.M)
        version=version.group(1) if version else keg.name.split('_')[0]
        shutil.copy2(formula,metadata/(package+'.rb'))
        receipt=json.loads((keg/'INSTALL_RECEIPT.json').read_text())
        if isinstance(receipt.get('source'),dict):receipt['source'].pop('path',None)
        (metadata/(package+'-receipt.json')).write_text(json.dumps(receipt,indent=2))
        matches=list(re.finditer(r'^\s*url "([^"]+)"',text,re.M))
        for index,match in enumerate(matches):
            block=text[match.end():matches[index+1].start() if index+1<len(matches) else len(text)]
            checksum=re.search(r'^\s*sha256 "([0-9a-f]{64})"',block,re.M)
            url=match.group(1).replace('#{version}',version)
            if checksum:add(package+('' if index==0 else '-resource-'+str(index)),url,checksum.group(1))
            elif index==0 and url.endswith('.git'):
                revision=re.search(r'revision: "([0-9a-f]{40})"',block)
                if not revision:raise ValueError('Git source has no exact revision: '+package)
                gitdir=cache/(package+'.git')
                if not gitdir.exists():
                    subprocess.run(['git','init','--bare',str(gitdir)],check=True,capture_output=True)
                    subprocess.run(['git','-C',str(gitdir),'fetch','--depth=1',url,revision.group(1)],check=True,capture_output=True,timeout=180)
                commit=subprocess.check_output(['git','-C',str(gitdir),'rev-parse','FETCH_HEAD'],text=True).strip()
                if commit!=revision.group(1):raise ValueError('Git source revision mismatch')
                archive=output/(package+'.tar.gz')
                with archive.open('wb') as f:subprocess.run(['git','-C',str(gitdir),'archive','--format=tar.gz','--prefix='+package+'/',commit],stdout=f,check=True)
                requests.append({'name':package,'url':url,'git_revision':commit,'sha256':sha(archive),'archive':archive.name})
            elif index==0:raise ValueError('Source checksum missing: '+package)
    # Python package source distributions carry their vendored source/build files.
    manifest=json.loads((internal/'security-manifest.json').read_text())
    for package in ('pillow','pyinstaller'):
        version=next(v for n,v in manifest['packages'].items() if n.lower()==package)
        data=json.load(urllib.request.urlopen('https://pypi.org/pypi/'+package+'/'+version+'/json',timeout=30))
        source=next(f for f in data['urls'] if f['packagetype']=='sdist')
        add(package+'-'+version,source['url'],source['digests']['sha256'])
    # LGPL/GPL source obligations include HandBrake's statically linked contribs.
    def fetch(request):
        if request.get('archive'):return request
        filename=request['name']+'--'+Path(urllib.parse.urlparse(request['url']).path).name
        archive=output/filename;cached=cache/(request['sha256'] or filename)
        if not cached.exists() or (request['sha256'] and sha(cached)!=request['sha256']):
            temporary=cached.with_name(cached.name+'.partial')
            subprocess.run(['curl','--fail','--location','--silent','--show-error','--retry','2','--connect-timeout','20','--max-time','240','--proto','=https','--output',str(temporary),request['url']],check=True,capture_output=True,timeout=750)
            if request['sha256'] and sha(temporary)!=request['sha256']:raise ValueError('Source checksum mismatch: '+request['name'])
            temporary.replace(cached)
        shutil.copyfile(cached,archive);return {**request,'sha256':sha(archive),'archive':filename}
    results=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(fetch,r):r for r in requests}
        for future in as_completed(futures):
            result=future.result();results.append(result);print('Verified source: '+result['name'],flush=True)
    hb=next(r for r in results if r['name'].startswith('handbrake-'))
    contribs=[]
    with tarfile.open(output/hb['archive']) as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith('/module.defs'):continue
            component=member.name.split('/')[-2]
            if component not in {'ffmpeg','x265','x265_8bit','x265_10bit','x265_12bit','libdovi'}:continue
            text=archive.extractfile(member).read().decode();url=re.search(r'^\w+\.FETCH\.url\s*=\s*(https://\S+)',text,re.M);checksum=re.search(r'^\w+\.FETCH\.sha256\s*=\s*([0-9a-f]{64})',text,re.M)
            if url and checksum and checksum.group(1) not in {r['sha256'] for r in contribs}:
                contribs.append({'name':'handbrake-contrib-'+component,'url':url.group(1),'sha256':checksum.group(1)})
    for request in contribs:results.append(fetch(request));print('Verified source: '+request['name'],flush=True)
    # Pillow bundles a FriBiDi shim; provide the version identified by its SBOM
    # as well as the dynamically linked media-tool version already collected.
    versions={component['version']
              for sbom in (internal/'licenses/pillow').rglob('*.cdx.json')
              for component in json.loads(sbom.read_text()).get('components',[])
              if component.get('name','').casefold()=='fribidi'}
    if len(versions)!=1 or not re.fullmatch(r'\d+\.\d+\.\d+',next(iter(versions))):
        raise ValueError('Pillow SBOM must identify the exact FriBiDi source version')
    fribidi_version=versions.pop()
    fribidi={'name':'pillow-fribidi-'+fribidi_version,'url':f'https://github.com/fribidi/fribidi/releases/download/v{fribidi_version}/fribidi-{fribidi_version}.tar.xz','sha256':None}
    results.append(fetch(fribidi))
    shutil.copytree(internal/'MediaTools/licenses',output/'licences',dirs_exist_ok=True)
    shutil.copytree(internal/'licenses',output/'runtime-notices',dirs_exist_ok=True)
    shutil.copytree(internal/'ExifTool',output/'embedded-exiftool-source',dirs_exist_ok=True)
    shutil.copyfile(internal/'MediaTools/manifest.json',output/'MEDIA_TOOL_PROVENANCE.json')
    (output/'SOURCES.json').write_text(json.dumps(sorted(results,key=lambda r:r['name']),indent=2)+'\n')
    (output/'README.txt').write_text('These archives are the upstream sources matching the distributed media tools. Sources remain under their original licences. Exact Homebrew build recipes and receipts are in build-recipes/. HandBrake contrib sources and patches/build definitions are supplied with its archive. Veronica packaging/relocation scripts are included in the same GitHub release source tag. No upstream source code was changed by relocation: Mach-O load paths and signatures were adjusted by scripts/bundle_media_tools.py. Runtime licence notices and Pillow component SBOMs are included.\n')
    print('Source archives verified: '+str(len(results)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--engine',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);a=p.parse_args();collect(a.engine,a.output,a.cache)
