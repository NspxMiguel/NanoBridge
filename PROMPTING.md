# Getting good output

Everything here was learned by generating, looking, and changing one thing at a
time. Where a claim has a number behind it, the number is in the repository's
history.

## The one rule that matters most: say what you do **not** want

The model adds things nobody asked for — a drop shadow, a patch of ground under
the character, a decorative border, a caption, a mockup frame. Each of those
ruins a sprite, and none of them go away by asking for "a clean sprite".

They go away by naming them:

> …no shadow, no floor, no ground, no border, no frame, no text, no watermark,
> no mockup, no extra objects.

NanoBridge's built-in templates already carry that list, which is most of why
`sprite` beats `gen` for sprites. When you write your own prompt with `gen`,
carry it yourself.

## Match the tool to the ask

| The ask | Use | Why not the other |
| --- | --- | --- |
| one thing | `sprite` | — |
| a few characters that belong together | `cast` | one prompt per character gives four unrelated art styles |
| animate something **already generated** | `animate` | `sheet` draws a *new* character from text; it will not be your sprite |
| an animation of something that doesn't exist yet | `sheet` | — |
| options to pick from | `variations` | asking once and retrying is the expensive loop |
| a repeating surface | `texture` | `gen` gives a picture *of* a surface, centred, with edges that don't meet |
| lighting a sprite | `normal` | local, no quota |

Picking wrong is the most common reason output disappoints. Asking `sheet` to
animate an existing character is the big one: it silently gives you a different
character, and it looks like the model "failed" when it did exactly what it was
told.

## Writing the subject

**Be concrete about the silhouette, vague about the rest.** A sprite is read at
32 pixels; what survives is the outline.

- Weak: `a warrior`
- Better: `a stocky warrior with a round shield and a short axe`
- Worse again: `a warrior, noble bearing, tragic past, weathered by years of war`
  — backstory does not draw.

**Name the pose when it matters.** `facing the camera`, `side view, facing
right`, `three-quarter view`. Without it you get whatever the model likes, and
across several sprites that means several different angles.

**One subject.** "a knight and his horse" gives you a scene you cannot cut into
two sprites. Generate them separately and use `pack_atlas`.

## Style

`--style` takes a keyword (`pixel`, `flat`, `cartoon`, `3d`, `realistic`,
`sketch`) or any free text. Free text wins when you know what you want:

```bash
nanobridge sprite "a healing potion" --style "flat vector, thick black outline, warm palette"
```

The keyword is a whole sentence under the hood. Free text replaces that
sentence, so include the parts you still want: outline weight, palette, shading.

**Pixel art needs `--pixels`.** Style alone gives *pixel-art-looking* art at
1024px — smooth curves pretending to be pixels. `--pixels 32` resamples to a
real 32×32 grid, and `--zoom 8` scales it back up with hard edges for viewing.

## Animation

The `action` is the whole animation, described as a loop:

- Weak: `walking`
- Better: `a walk cycle: left leg forward, passing pose, right leg forward, passing pose`
- Also good: `squashes down on impact and springs back up, returning to the start`

Say **"returning to the start"** or **"a clean loop"** when it should loop. The
model otherwise draws a sequence that ends somewhere else, and the GIF jumps.

**Fewer frames are more reliable.** `4x1` holds together far more often than
`6x2`. The frames drift — by frame ten the character has quietly changed. Ask
for four good frames and animate again for the next four.

Check the frames, not the GIF. NanoBridge writes both because a bad frame is
invisible at 10fps and obvious side by side.

## Editing and keeping a character

Reference beats description. Once a sprite exists, do not describe it again —
hand it over:

```bash
nanobridge edit hero.png "give it a red cape, keep everything else identical"
nanobridge animate hero.png "waves its hand" --grid 4x1
```

`keep everything else identical` earns its place. Without it, "add a cape"
becomes "here is a different character, with a cape".

For several rounds on the same image, pass the `conversation` token back. The
model then holds the character across turns instead of re-inventing it.

## When output is wrong

**Wrong drawing → change the prompt.** Regenerating an unchanged prompt mostly
gives you the same thing again.

**Right drawing, wrong crop or background → fix it locally.** `cut`, `slice`,
`atlas`, `normal` and `tile --repair` cost nothing and touch no quota. Do not
burn a generation on something Pillow can do.

**The model answers in words instead of drawing** ("I can't create that…") →
it usually read the prompt as a question or a policy problem. Rephrase as a
description of an object, not a request about one. `--retries` already retries
this automatically.

**Everything looks the same across attempts** → the model converges. That is
what `variations` exists for: it pushes each attempt in a different direction on
purpose.

## Costs

Every generation spends the Gemini plan's quota; `doctor` shows what is left.
The local commands — `cut`, `slice`, `atlas`, `normal`, `tile`, `palette` —
spend nothing. A good habit: generate once, then iterate locally.
