from base64 import b64encode
from io import BytesIO

from click import confirm
from PIL import Image, ImageChops

_SIZE = 500
_BORDER = 10


def offer(name, source, images):
    images = list(map(lambda image: Image.open(BytesIO(image)).convert("RGB") if image else None, images))
    images[0] = images[0] or Image.new("RGB", images[1].size)
    if images[0].size == images[1].size:
        actual = 0
        total = 0
        for pixel in ImageChops.difference(*images).getdata():
            actual += sum(pixel)
            total += 255 * 3
        if actual / total < 0.05:
            return False
    height = min(_SIZE, max(images[0].size[1], images[1].size[1]))
    canvas = Image.new("RGB", (_SIZE * len(images) + _BORDER * len(images) - 1, height))
    x = 0
    label = ""
    for image in images:
        size = f"{image.size[0]}x{image.size[1]}"
        label += f"{size:36}"
        image.thumbnail((_SIZE, _SIZE), Image.ANTIALIAS)
        canvas.paste(image, (x, 0))
        x += _SIZE + _BORDER
    buf = BytesIO()
    canvas.save(buf, format="webp", lossless=True)
    print(f"\x1B]1337;File=name={b64encode(name.encode()).decode()};height={height}px;inline=1:{b64encode(buf.getvalue()).decode()}\x07")
    print(label)
    return confirm(f"{name}: use the image from {source}")
