# CBZ volume packaging

Python 3.10+ is required. Packaging uses the standard library; downloading covers
also needs `python -m pip install -r scripts/cbz/requirements-covers.txt`.
Run these examples from the repository root, replacing `../library` with the
library directory supplied for the packaging task.

```powershell
# Inspect chapter coverage and covers without writing anything or downloading.
./build-cbz.ps1 -RootPath ../library -Volume 1 -ValidateOnly

# Fetch configured cover URLs explicitly (validates image bytes and dimensions).
python scripts/cbz/cbz.py covers --config ../library/volumes.json --volume 1

# Build into another library root. Existing archives cause an error.
./build-cbz.ps1 -RootPath ../library -OutputPath ../output `
  -Volume 1 -ReportPath ../library/packaging-report.json

# Equivalent portable command; use plan instead of build for validation.
python scripts/cbz/cbz.py build --config ../library/volumes.json `
  --root ../library --output ../output --volume 1

python scripts/cbz/cbz.py verify '../output/CBZ/Example Series'
python -m unittest discover -s test/cbz -v
```

`--root` defaults to the working directory. `--output` defaults to the source
root; each series' `outputFolder` is relative to that root. For example,
`--output ../output` plus `outputFolder: CBZ/Example` writes `../output/CBZ/Example`.
`--assets-root` defaults to the settings file's directory. It contains both
explicit `cover` paths and the `covers/` directory used by `coverFolder`.
Keep `covers/...` beside the settings to resolve assets without `--assets-root`.
That flag remains available for separate assets.
The PowerShell wrapper defaults `-ConfigPath` to `volumes.json` under `-RootPath`.

PowerShell preserves `-Series`, `-Volume`/`-SelectedVolume`, `-AllowPartial`,
`-Force`, and `-ValidateOnly`. Downloads now require `-DownloadCovers`;
`-NoCoverDownload` is accepted and suppresses that explicit download flag.
Python uses `--series`, `--volume`, `--allow-partial`, and `--force`.
The wrapper forwards the CLI exit code.

## Settings

Keep series settings in the local library directory, outside the repository.
Use `volumes.json` or a series-specific filename, passing its path through
`--config` or `-ConfigPath`. Cached covers and source URLs are reused between runs.
For a new series, save a local JSON file with this structure:

```json
{
  "series": [{
    "title": "Example Series",
    "folder": "Example Series",
    "coverFolder": "Example Series",
    "volumes": [
      {"volume": 1, "firstChapter": 1, "lastChapter": 7}
    ]
  }]
}
```

| Field | Meaning |
| --- | --- |
| `series[].title`, `folder` | Display name and source directory relative to `--root` |
| `chapterFolderPattern` | Default `Ch. {chapter}`; use e.g. `Chapter {chapter}.cbz` for chapter archives |
| `outputFolder` | Destination directory relative to `--output`; default `CBZ/<title>` |
| `outputFilePattern` | Default `{title} v{volume:02d}.cbz`; legacy `{volume:00}` also works |
| `minImagesPerChapter` | Default 1; a chapter below the threshold is omitted and reported |
| `coverFolder` | Look for exactly one `covers/<folder>/vNN.<image extension>` under `--assets-root` |
| `requireCover` | Default true; set false for a deliberately coverless edition |
| `writer`, `artist`, `publisher`, `genre`, `summary` | ComicInfo metadata; volume-level values override series values |
| `language`, `manga` | Default `en` and `YesAndRightToLeft`; use `No` for non-manga |
| `volumeCount` | Optional verified total for ComicInfo Count; omitted for an unknown/ongoing total |
| `volumes[].volume` | Nonnegative integer; supports volume 0 |
| `firstChapter`, `lastChapter` | Inclusive integer boundaries |
| `chapters` | Explicit numeric chapter list instead of a range; its order is preserved |
| `additionalChapters` | Required extras added to the selection |
| `optionalChapters` | Extras included if present; absence does not mark a volume partial |
| `cover`, `coverUrl` | Explicit asset-relative cover path and researched HTTP(S) image URL |
| `title`, `year`, `isbn`, `web` | Optional volume metadata (ISBN maps to GTIN) |
| `knownIssues` | Unresolved issues that mark a volume incomplete |
| `edition`, `sources` | Research provenance retained in settings; not inferred by the packager |

Ranges plus extras are sorted by decimal chapter number. Negative source labels
are supported. Chapters cannot be assigned twice, including across volumes.
Pages are discovered recursively and naturally sorted; chapter CBZ/ZIP inputs
are CRC-checked and their old ComicInfo files are excluded. CBR input and
arbitrary chapter labels are not supported by the new CLI.

Paths in settings must stay within the chosen roots. Filenames are sanitized
for Windows. Sources are never deleted or edited. Default publication refuses
existing destinations; `--force` replaces an archive only after verification.
Publication uses a same-directory temporary file and a hard link for exclusive
creation, so the destination filesystem must support hard links (e.g. NTFS).

## Coverage and verification

Missing required chapters, covers, and `knownIssues` prevent building that volume
unless `--allow-partial` is given. Partial files end in `.incomplete.cbz` and
record their problems in ComicInfo Notes. A volume with no chapter pages is
never built. Optional extras below the minimum page threshold are reported if
they contain any pages. Other ready volumes may still build in a mixed run.

`plan` reports expected/included chapters, unassigned local chapters, problems,
existing output paths, and page counts. Use `--report <file.json>` to save those
details; this is an explicit write even in plan mode. Inventory of unassigned
chapters applies to immediate children matching `chapterFolderPattern` with
the literal `{chapter}` placeholder. Check other folders separately.

Exit codes: **0** success, **1** absent/incomplete volumes skipped, **2** invalid
settings, conflicts, I/O errors, or failed verification. Existing files are
reported in `plan`; `build` refuses conflicts before writing any archives.
Reports describe the current invocation and are only written if it completes
without a fatal error. They replace the explicitly chosen report file.

Every new archive passes ZIP CRC, entry/order, XML PageCount, and cover-reference
checks before publication. `verify` checks existing CBZs for CRC, duplicate
entries, ComicInfo page count, and cover references. It does not establish scan
completeness or bibliographic accuracy.

The metadata workflow is in the repository skill
[cbz-volumes](../../.agents/skills/cbz-volumes/SKILL.md). ComicInfo numbering follows
the [Anansi documentation](https://anansi-project.github.io/docs/comicinfo/documentation):
book number goes in `Number`; `Volume` is not set to the manga book number.

## Local library data

Only the current generic tools, documentation, tests, and skill are maintained
in this repository. Volume settings, cached covers, source images, generated
archives, and run reports belong in the library directory chosen for the task.
