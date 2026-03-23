#!/usr/bin/env python3
"""Generate a corpus of mobile-screenshot-like test images with ~630 chars / ~106 words each."""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Text corpus – 24 distinct ~630-char / ~106-word snippets of lorem ipsum
# ---------------------------------------------------------------------------
SNIPPETS = [
    # 1
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Curabitur pretium tincidunt lacus. Nulla mauris tincidunt sem feugiat facilisis. Fusce dapibus tellus ac cursus commodo tortor mauris nibh.",
    # 2
    "Pellentesque habitant morbi tristique senectus et netus et malesuada fames ac turpis egestas. Vestibulum tortor quam feugiat vitae ultricies eget tempor sit amet ante. Donec eu libero sit amet quam egestas semper. Aenean ultricies mi vitae est mauris placerat eleifend leo. Quisque sit amet est et sapien ullamcorper pharetra vestibulum erat wisi. Condimentum sed commodo vitae ornare sit amet wisi. Aenean fermentum risus id tortor integer ullamcorper lorem ipsum. Proin vel ante orci tempus eleifend magna.",
    # 3
    "Quisque sit amet est et sapien ullamcorper pharetra vestibulum erat wisi. Condimentum sed commodo vitae ornare sit amet wisi. Aenean fermentum risus id tortor integer ullamcorper lorem ipsum. Donec aliquet metus vitae enim feugiat sit amet sodales dui dictum. Praesent commodo cursus magna vel scelerisque nisl consectetur et vivamus. Sagittis lacus vel augue laoreet rutrum faucibus dolor auctor duis mollis est. Non commodo luctus nisi erat porttitor venenatis proin sodales gravida.",
    # 4
    "Cras mattis consectetur purus sit amet fermentum. Cras justo odio dapibus ac facilisis in egestas eget quam. Morbi leo risus porta ac consectetur ac vestibulum at eros praesent. Commodo cursus magna vel scelerisque nisl consectetur et vivamus sagittis lacus. Vel augue laoreet rutrum faucibus dolor auctor duis mollis est non commodo. Luctus nisi erat porttitor ligula donec sed odio dui curabitur blandit. Tempus porttitor integer posuere cubilia curae proin vel ante orci.",
    # 5
    "Maecenas faucibus mollis interdum sed posuere consectetur est at lobortis donec. Ullamcorper nulla non metus auctor fringilla nullam quis risus eget urna. Mollis ornare vel eu leo cum sociis natoque penatibus et magnis. Dis parturient montes nascetur ridiculus mus nullam id dolor id nibh. Ultricies vehicula ut id elit fermentum blandit cursus phasellus accumsan velit. Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere. Cubilia curae donec velit neque auctor aliquam.",
    # 6
    "Fusce dapibus tellus ac cursus commodo tortor mauris condimentum nibh ut. Fermentum massa justo sit amet risus etiam porta sem malesuada magna. Mollis euismod donec sed odio dui curabitur blandit tempus porttitor nullam. Quis risus eget urna mollis ornare vel eu leo integer posuere. Erat ante ipsum primis in faucibus orci luctus et ultrices posuere. Cubilia curae proin vel ante a orci tempus eleifend ut magna. Lorem ipsum dolor sit amet consectetur adipiscing elit gravida.",
    # 7
    "Integer posuere erat ante volutpat dapibus posuere velit aliquet cras justo. Odio dapibus ac facilisis in egestas eget quam morbi leo risus. Porta ac consectetur ac vestibulum at eros fringilla praesent commodo cursus. Magna vel scelerisque nisl consectetur et vivamus sagittis lacus vel augue. Laoreet rutrum faucibus dolor auctor duis mollis est non commodo luctus. Nisi erat porttitor ligula eget lacus congue mauris fermentum volutpat faucibus. Augue arcu eleifend montes nascetur volutpat tortor sodales.",
    # 8
    "Aenean lacinia bibendum nulla sed consectetur etiam porta sem malesuada magna. Mollis euismod donec sed odio dui curabitur blandit tempus porttitor integer. Quis risus eget urna mollis ornare vel eu leo cum sociis. Natoque penatibus et magnis dis parturient montes nascetur ridiculus mus nullam. Id dolor id nibh ultricies vehicula ut id elit phasellus accumsan. Cursus velit vestibulum ante ipsum primis in faucibus orci luctus ultrices. Posuere cubilia curae integer erat porttitor ligula dapibus.",
    # 9
    "Vivamus magna justo lacinia eget consectetur sed convallis at tellus cras. Mattis consectetur purus sit amet fermentum. Cras justo odio dapibus ac facilisis egestas eget quam morbi leo. Risus porta ac consectetur ac vestibulum at eros praesent commodo cursus. Magna vel scelerisque nisl consectetur et vivamus sagittis lacus vel augue. Laoreet rutrum faucibus dolor auctor duis mollis est non commodo luctus. Nisi erat porttitor integer ullamcorper lorem ipsum dolor sit amet.",
    # 10
    "Cum sociis natoque penatibus et magnis dis parturient montes nascetur ridiculus mus. Aenean lacinia bibendum nulla sed consectetur etiam porta sem malesuada magna. Mollis euismod donec sed odio dui curabitur blandit tempus porttitor nullam. Quis risus eget urna mollis ornare vel eu leo integer posuere erat. Ante volutpat dapibus posuere velit aliquet cras justo odio facilisis egestas. Eget quam morbi leo risus porta consectetur vestibulum eros accumsan gravida. Nibh integer ullamcorper lorem ipsum dolor.",
    # 11
    "Phasellus viverra nulla ut metus varius laoreet quisque rutrum aenean imperdiet. Etiam ultricies nisi vel augue curabitur ullamcorper ultricies nisi nam eget. Dui etiam rhoncus phasellus imperdiet nunc vitae tincidunt diam quam felis. Iaculis vel pretium vel facilisi nec nulla facilisi morbi in ipsum. Integer nisi risus posuere facilisis est duis ac diam mollis interdum. Donec ullamcorper nulla non metus auctor fringilla nullam quis risus urna. Mollis ornare vel eu vestibulum integer posuere.",
    # 12
    "Donec id elit non mi porta gravida at eget metus fusce. Dapibus tellus ac cursus commodo tortor mauris condimentum nibh ut. Fermentum massa justo sit amet risus etiam porta sem malesuada magna. Mollis euismod donec sed odio dui curabitur tempus porttitor nullam quis. Risus eget urna mollis ornare vel eu leo integer posuere erat. Ante volutpat dapibus posuere velit aliquet cras justo odio dapibus. Ac facilisis egestas eget quam morbi leo risus porta tortor.",
    # 13
    "Malesuada fames ac ante ipsum primis in faucibus vestibulum tortor quam. Feugiat vitae ultricies eget tempor sit amet ante donec eu libero. Quam egestas semper aenean ultricies mi vitae est mauris placerat eleifend. Leo quisque sit amet est et sapien ullamcorper pharetra vestibulum erat. Wisi condimentum sed commodo vitae ornare sit amet wisi aenean fermentum. Risus id tortor integer ullamcorper lorem ipsum donec aliquet metus vitae. Enim feugiat sit amet sodales dui dictum praesent.",
    # 14
    "Nullam dictum felis eu pede mollis pretium integer tincidunt cras dapibus. Vivamus elementum semper nisi aenean vulputate eleifend tellus aenean leo ligula. Porttitor ut lacus nulla tincidunt dui vitae orci mauris porta justo. Cum sociis natoque penatibus et magnis dis parturient montes nascetur ridiculus. Donec quam felis ultricies nec pellentesque eu pretium quis sem nulla. Consequat massa quis enim donec pede justo fringilla vel aliquet nec. Vulputate vitae nisl aenean lectus elit fermentum pharetra.",
    # 15
    "Vulputate vitae nisl aenean lectus elit fermentum nec pharetra non enim. Augue vestibulum quam sodales vel mauris quisque porttitor curabitur lacus purus. Quis nibh pretium iaculis justo in libero facilisis quam est efficitur. Porta nisi vitae scelerisque ante viverra sodales accumsan leo sed lacinia. Nisl gravida lorem tincidunt maximus nam accumsan felis nisi curabitur tristique. Lorem a purus semper aliquam scelerisque tortor maximus proin vel ante. Orci tempus eleifend magna ut lorem ipsum.",
    # 16
    "Proin gravida nibh vel velit auctor aliquet aenean sollicitudin lorem quis. Bibendum elit morbi tristique senectus et netus malesuada fames ac turpis. Egestas vitae nisi nibh feugiat consectetuer ligula donec totor nunc semper. Massa fusce ac turpis quis ligula lacinia aliquet mauris ipsum viverra. Et arcu duis vitae odio pellentesque faucibus est praesent ligula orci. Porttitor eget malesuada adipiscing lacus vel varius nisl condimentum dictum. Nullam quis dolor id nibh ultricies vehicula ut.",
    # 17
    "Aliquam erat volutpat nam dui mi tincidunt quis accumsan porttitor facilisis. Luctus metus pede neque sodales dapibus accumsan laoreet enim leo vehicula. Faucibus morbi tortor wisi dignissim blandit iaculis class aptent taciti sociosqu. Ad litora torquent per conubia nostra inceptos hymenaeos mauris in erat justo. Faucibus orci luctus et ultrices posuere cubilia curae proin vel ante. Orci tempus eleifend ut et magna lorem ipsum dolor sit amet. Consectetur adipiscing elit sed do eiusmod tempor.",
    # 18
    "Etiam sit amet orci eget eros faucibus tincidunt duis leo sem congue. Mauris fermentum volutpat faucibus augue arcu eleifend montes volutpat tortor sociis. Natoque penatibus magnis parturient nascetur ridiculus mus praesent turpis ipsum porttitor. Molestie bibendum fringilla sagittis venenatis mollis tristique adipiscing nunc congue nisl. Vitae hendrerit dictum lacus nulla mauris tincidunt sem feugiat facilisis fusce. Dapibus tellus ac cursus commodo tortor mauris condimentum nibh ut. Fermentum massa justo amet risus blandit.",
    # 19
    "In dui magna posuere eget vestibulum et tempus posuere cubilia curae. Proin pharetra nonummy pede mauris eros donec ligula quisque aliquet lorem. Amet dictum sit amet justo donec enim diam vulputate ut pharetra. Sit amet aliquam id diam maecenas ultricies mi eget mauris pharetra. Et ultrices neque ornare aenean euismod elementum nisi quis eleifend quam. Adipiscing vitae proin sagittis nisl rhoncus mattis rhoncus urna neque viverra. Justo nec sodales purus accumsan gravida lorem.",
    # 20
    "Nam pretium turpis et arcu duis vitae odio pellentesque faucibus est praesent. Ligula porttitor eget malesuada adipiscing lacus vel varius nisl molestie pretium. Vulputate sapien nec sagittis aliquam malesuada bibendum arcu vitae elementum curabitur. Netus et malesuada fames ac turpis egestas donec odio justo sollicitudin. Ut suscipit nec ante nisi congue semper tempus lorem volutpat condimentum. Augue vitae pellentesque diam volutpat commodo sed egestas quam morbi leo. Risus porta ac consectetur vestibulum eros.",
    # 21
    "Quisque velit nisi pretium ut lacinia in elementum id enim nullam. Quis risus sed vulputate odio ut enim blandit volutpat maecenas volutpat. Blandit aliquam etiam erat velit scelerisque in dictum non consectetur a. Erat nam at lectus urna duis convallis convallis tellus id interdum. Velit aliquet sagittis id consectetur purus ut faucibus pulvinar elementum integer. Enim neque volutpat ac tincidunt vitae semper quis lectus nulla at. Volutpat diam ut venenatis tellus in metus vulputate.",
    # 22
    "Mauris blandit aliquet elit eget tincidunt nibh pulvinar a nullam quis. Ante orci ultrices odio amet nam arcu sed gravida accumsan tortor. Porta nibh venenatis cras sed felis eget velit aliquet sagittis id. Lorem donec vel est orci volutpat nullam curabitur gravida arcu vel. Tortor consequat id porta nibh venenatis cras sed felis eget velit. Aliquet sagittis id consectetur purus rhoncus ultricies tellus a arcu posuere. Erat ante volutpat dapibus velit cras odio.",
    # 23
    "Sed porttitor lectus nibh curabitur arcu erat accumsan id implicita orci nibh. Venenatis cras sed felis eget velit aliquet sagittis praesent sapien massa. Convallis a pellentesque nec egestas non nisi mauris blandit aliquet elit. Eget tincidunt nibh pulvinar nullam nunc id cursus metus aliquam eleifend. Mi in nulla posuere sollicitudin aliquam ultrices sagittis orci a scelerisque. Purus semper eget duis luctus accumsan odio pellentesque habitant morbi senectus. Netus malesuada fames turpis egestas vestibulum.",
    # 24
    "Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere cubilia. Curae donec velit neque auctor sit amet aliquam vel ullamcorper sit. Amet justo donec enim diam vulputate ut pharetra sit amet aliquam. Id diam maecenas ultricies mi eget mauris pharetra et ultrices neque. Ornare aenean euismod elementum nisi quis eleifend quam adipiscing vitae proin. Sagittis nisl rhoncus mattis rhoncus urna neque viverra justo nec condimentum. Augue vitae pellentesque diam volutpat commodo sed.",
]

# ---------------------------------------------------------------------------
# Rendering parameters  (tweaked to give ~630 chars / ~106 words per image)
# ---------------------------------------------------------------------------
FONT_PATH     = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD     = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_SIZE     = 28          # large enough to be legible for Tesseract
IMG_W         = 720         # typical Android portrait width
IMG_BG        = (255, 255, 255)
TEXT_COLOR    = (30, 30, 30)
STATUS_BG     = (245, 245, 245)
STATUS_H      = 48
PADDING       = 36
LINE_SPACING  = 1.35        # multiplier over font size
TITLE_PAD     = 20          # extra space below title

TARGET_WORDS = 106

# Extra filler sentences rotated to pad snippets that are too short
_FILLER = (
    "Donec aliquet metus vitae enim feugiat sit amet sodales dui dictum praesent.",
    "Proin vel ante a orci tempus eleifend ut et magna lorem ipsum dolor.",
    "Nulla mauris tincidunt sem feugiat facilisis fusce dapibus tellus ac cursus.",
    "Cum sociis natoque penatibus magnis parturient montes nascetur ridiculus mus nullam.",
    "Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere cubilia.",
    "Aenean fermentum risus id tortor integer ullamcorper lorem ipsum donec aliquet.",
    "Phasellus accumsan cursus velit vestibulum ante ipsum primis faucibus orci luctus.",
    "Morbi leo risus porta ac consectetur vestibulum at eros praesent commodo cursus.",
)


def pad_to_target(text: str, target: int = TARGET_WORDS) -> str:
    words = text.split()
    i = 0
    while len(words) < target:
        filler_words = _FILLER[i % len(_FILLER)].split()
        needed = target - len(words)
        words.extend(filler_words[:needed])
        i += 1
    return " ".join(words)


OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def make_image(index: int, text: str) -> Path:
    font        = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    font_bold   = ImageFont.truetype(FONT_BOLD, FONT_SIZE - 2)
    font_small  = ImageFont.truetype(FONT_PATH, FONT_SIZE - 8)

    usable_w = IMG_W - 2 * PADDING
    line_h   = int(FONT_SIZE * LINE_SPACING)

    # Word-wrap the body text
    wrapped_lines = textwrap.wrap(text, width=int(usable_w / (FONT_SIZE * 0.52)))

    title = f"Nota #{index:02d}"

    # Calculate total height
    total_text_h = (len(wrapped_lines) * line_h
                    + FONT_SIZE          # title
                    + TITLE_PAD
                    + 2 * PADDING)
    img_h = max(total_text_h + STATUS_H, 400)

    img  = Image.new("RGB", (IMG_W, img_h), IMG_BG)
    draw = ImageDraw.Draw(img)

    # Status bar
    draw.rectangle([0, 0, IMG_W, STATUS_H], fill=STATUS_BG)
    draw.text((PADDING, 14), "9:41", font=font_small, fill=(80, 80, 80))
    draw.text((IMG_W - PADDING - 60, 14), "100%", font=font_small, fill=(80, 80, 80))

    # Thin separator below status bar
    draw.line([(0, STATUS_H), (IMG_W, STATUS_H)], fill=(220, 220, 220), width=1)

    # Title
    y = STATUS_H + PADDING
    draw.text((PADDING, y), title, font=font_bold, fill=(0, 0, 0))
    y += FONT_SIZE + TITLE_PAD

    # Body lines
    for line in wrapped_lines:
        draw.text((PADDING, y), line, font=font, fill=TEXT_COLOR)
        y += line_h

    out_path = OUT_DIR / f"test_{index:02d}.jpg"
    img.save(out_path, "JPEG", quality=92)
    return out_path


def main() -> None:
    print(f"Generating {len(SNIPPETS)} images → {OUT_DIR}\n")
    for i, snippet in enumerate(SNIPPETS, start=1):
        text = pad_to_target(snippet)
        path = make_image(i, text)
        chars = len(text)
        words = len(text.split())
        print(f"  [{i:02d}] {path.name}  chars={chars}  words={words}")
    print(f"\nDone. {len(SNIPPETS)} images saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
