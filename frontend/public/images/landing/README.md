# Landing photograph

`secretary-desk.webp` is a 1024 × 1024 WebP derivative of `images/main_pic3.png`
in this repository — a project-owned asset supplied by the product owner, kept
under the same terms as the rest of `images/` rather than the code's Apache-2.0
license.

- Source: `images/main_pic3.png` (1536 × 1024)
- Processing: centre-cropped to a square around the subject (`x0 = 446`),
  encoded as WebP; no generated or retouched content.

The square source is deliberate: the hero frame is 0.96 on desktop and 1.14 on
phones, so `object-fit: cover` trims only a little at either end. The frame's
`object-position` biases the vertical crop upward so the phone breakpoint keeps
the subject's head in view.

The app imports the image statically so Next.js emits an immutable, hashed URL
and a small blur placeholder. No external image request at runtime.
