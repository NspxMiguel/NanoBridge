# Uma Fase

A one-screen platformer where **every drawing came out of NanoBridge**. It exists
to answer the only question that matters about an asset tool: does the output
actually work in a game?

```bash
cd examples/uma-fase && python3 -m http.server 8756
# depois abra http://localhost:8756
```

Arrows or `A`/`D` to move, `space` to jump, land on the mushroom's head.

## What made each asset

```bash
# o elenco, numa paleta só, empacotado num atlas com manifesto Phaser
nanobridge cast \
  "a cheerful cartoon plumber in a red cap and blue overalls, standing, side view facing right" \
  "a friendly brown mushroom enemy with big eyes and little feet, side view facing left" \
  "a shiny gold coin with a star, front view, bright yellow" \
  "an orange brick block with rivets, square, front view" \
  --style pixel --palette endesga32 --size 96 --pixels 24 -f phaser

# o ciclo de corrida, a partir do sprite que já existia
nanobridge animate hero.png \
  "a run cycle: right leg forward with arms swinging, passing pose, left leg forward, passing pose" \
  --grid 4x1 --frame-size 24 --pixels 24 --palette endesga32
```

The run cycle is the point of `animate`: it is **that** plumber running, not a new
plumber drawn from a description. Everything shares one palette because `cast`
locks it across the whole set.

## What the code does that the tool doesn't

The sky, hills, clouds and flag are drawn with canvas primitives — a generator is
the wrong tool for a gradient. The jump has coyote time and a jump buffer, and
the run cycle is driven by horizontal speed. Those are game-feel decisions, not
asset decisions.
