"""Explicit capture dates for media fixtures that are intended to be processed."""
from PIL import Image


def exif_date(value="2023:01:01 12:00:00"):
    exif = Image.Exif()
    exif[34665] = {36867: value}
    return exif
