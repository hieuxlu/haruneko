---
name: cbz-volumes
description: Package local manga or comic chapters into CBZ volumes and research edition-specific chapter boundaries, volume metadata, ISBNs, and covers. Use for volume settings, chapter coverage checks, cover collection, and ComicInfo verification.
---

# CBZ volumes

Use this repository's generic packager at `scripts/cbz/cbz.py` or the root
`build-cbz.ps1` wrapper. Resolve the repository root three directories above this
skill. Read [the CLI and settings reference](../../../scripts/cbz/README.md)
when creating settings or choosing flags. Keep volume settings beside the local
library, not in this repository. Determine the library location from the current
task and inspect its settings; do not assume a machine-specific path. Prefer
paths relative to the library inside settings, such as `covers/<series>/v01.jpg`.
Supply the library location through the CLI's root/config arguments. Use the
inline example in the CLI reference for a new series.

## Find volume metadata and covers

Identify the series and edition before choosing boundaries: original singles,
translated singles, omnibus, full-color, and revised editions can differ. Reuse
the user's chosen edition. If it is unspecified, inspect existing settings,
filenames, and covers; ask only if an unresolved choice changes the chapter map.

Check the existing settings, cached covers, and provenance sidecars first.
Reuse verified metadata and valid matching covers on later packaging runs;
do not repeat searches simply because more chapters have been downloaded.
During the initial cover lookup for a configured edition, collect and cache
covers for all configured volumes, including volumes without local chapters.
Persist their exact image URLs and product-page provenance in the settings so
later runs can fetch a missing file directly. Search again only for missing or
invalid metadata/assets, newly added volumes, an edition change, or a requested
refresh. If an unreleased cover is unavailable, record that gap rather than
substituting a different edition.

When research is needed, use available web tools. Start with publisher book
pages for ISBN, release date, creators, imprint, edition, and cover images:
[VIZ](https://www.viz.com/manga-books) and
[Shueisha's ISBN/title search](https://books.shueisha.co.jp/search/) are useful
for their respective editions. Follow the matching publisher product page and
inspect its actual cover image URL. Do not manufacture a CDN URL from an ISBN
or assume a Japanese cover represents an English edition.

For chapter boundaries, prefer a table of contents or publisher preview for
the exact book. Edition-specific chapter lists and specialist wikis can fill
gaps; cross-check ambiguous splits, bonus chapters, redraws, and renumberings.
For MediaWiki/Fandom images, page image lists can contain multiple editions;
select the matching image, then resolve its actual original file URL using
imageinfo or the file page. Search thumbnails are discovery aids, not evidence
that the selected image belongs to the right volume.

Record `edition` and `sources` in series settings. Each source record should
contain its URL, accessed date, what it supports, and any uncertainty. Put
per-volume provenance in that volume's `sources`, the matching product page in
`web`, ISBN in `isbn`, and the image URL in `coverUrl`. Preserve known migrated
sources, but do not describe old settings as newly verified. Record unresolved
numbering/boundaries as `knownIssues`; avoid inventing a mapping to fill a gap.

Use the `covers` command to download configured URLs. It requires Pillow,
validates decoded images and minimum dimensions, refuses to overwrite covers,
and writes an image provenance sidecar. Inspect cover images to confirm series,
volume, language/edition, orientation, and whether they are cropped or obstructed.
An existing cover is reused; replace it only when the user's task calls for it.

## Package and verify

Inspect local chapter labels and page layout before changing settings. Retain
decimal and negative labels exactly as source identifiers. Explicit `chapters`
lists preserve reading order; ranges plus extras sort numerically. Use
`optionalChapters` only for genuinely optional extras, not missing required
chapters. Separate uncollected chapters from published-volume mappings.

Run `plan` first with explicit source, asset, and destination roots. It performs
no writes unless `--report` is requested. Inspect missing and unassigned chapters
and check that the settings account for the intended reading material. Existing
CBZ chapter inputs use `chapterFolderPattern: "Ch. {chapter}.cbz"`; folder inputs
default to `Ch. {chapter}`. CBR sources need a separate conversion workflow.

Build with `build`, optionally selecting series and volumes. Use
`--allow-partial` only for a requested partial build; incomplete files are named
accordingly. Existing outputs require `--force`, which atomically replaces only
verified archives. Do not remove chapter sources or modify an existing library
beyond the user's requested packaging scope.

Keep covers first and mark only an actual cover as FrontCover. The packager
writes ComicInfo.xml and checks CRC, ordered entries, and page counts before
publishing. For metadata changes, consult the maintained
[ComicInfo documentation](https://anansi-project.github.io/docs/comicinfo/documentation).
`Number` holds the manga book number; use `volumeCount` only for a known edition
total. Set `language` and `manga` to match the material.

Use `verify` for existing outputs and retain a JSON report for requested batches.
Report built/partial/skipped volumes, remaining gaps or unassigned chapters,
metadata uncertainty, and the locations of archives and settings. ZIP validity
does not prove the original scans or chapter mapping are complete.
