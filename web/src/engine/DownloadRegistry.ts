import { MangaExportFormat } from './exporters/MangaExporterRegistry';
import { Key, Scope } from './SettingsGlobal';
import type { Directory, SettingsManager } from './SettingsManager';
import { SanitizeFileName, Store, type StorageController } from './StorageController';
import type { Chapter, Manga } from './providers/MangaPlugin';

export type DownloadSource = 'download' | 'scan';

export type DownloadRecord = {
    key: string;
    websiteIdentifier: string;
    mangaIdentifier: string;
    chapterIdentifier: string;
    websiteTitle: string;
    mangaTitle: string;
    chapterTitle: string;
    format: MangaExportFormat;
    relativePath: string;
    source: DownloadSource;
    updated: number;
};

type ScanDirectory = {
    handle: FileSystemDirectoryHandle;
    path: string[];
};

const formats = [
    { format: MangaExportFormat.CBZ, extension: '.cbz', kind: 'file' },
    { format: MangaExportFormat.EPUB, extension: '.epub', kind: 'file' },
    { format: MangaExportFormat.PDF, extension: '.pdf', kind: 'file' },
    { format: MangaExportFormat.RAWs, extension: '', kind: 'directory' },
] as const;

/** Persisted record of successfully exported chapters, with best-effort filesystem import. */
export class DownloadRegistry {

    private records: Map<string, DownloadRecord>;
    private loading: Promise<Map<string, DownloadRecord>>;

    public constructor(private readonly storage: StorageController, private readonly settingsManager: SettingsManager) {}

    public static GetKey(chapter: Chapter): string {
        return JSON.stringify([
            chapter.Parent?.Parent?.Identifier ?? '',
            chapter.Parent?.Identifier ?? '',
            chapter.Identifier,
        ]);
    }

    private async GetRecords(): Promise<Map<string, DownloadRecord>> {
        if (this.records) return this.records;
        if (!this.loading) {
            this.loading = this.storage.LoadPersistent<DownloadRecord[]>(Store.Downloads)
                .then(records => new Map((records ?? []).map(record => [ record.key, record ])));
        }
        this.records = await this.loading;
        return this.records;
    }

    public async IsStored(chapter: Chapter): Promise<boolean> {
        return (await this.GetRecords()).has(DownloadRegistry.GetKey(chapter));
    }

    public async MarkStored(chapter: Chapter, format: MangaExportFormat, relativePath: string, source: DownloadSource = 'download'): Promise<void> {
        const record: DownloadRecord = {
            key: DownloadRegistry.GetKey(chapter),
            websiteIdentifier: chapter.Parent?.Parent?.Identifier ?? '',
            mangaIdentifier: chapter.Parent?.Identifier ?? '',
            chapterIdentifier: chapter.Identifier,
            websiteTitle: chapter.Parent?.Parent?.Title ?? '',
            mangaTitle: chapter.Parent?.Title ?? '',
            chapterTitle: chapter.Title,
            format,
            relativePath,
            source,
            updated: Date.now(),
        };
        (await this.GetRecords()).set(record.key, record);
        await this.storage.SavePersistent(record, Store.Downloads, record.key);
        chapter.SetStored(true);
    }

    public GetOutputName(chapterTitle: string, format: MangaExportFormat): string {
        const extension = formats.find(candidate => candidate.format === format)?.extension ?? '';
        return SanitizeFileName(chapterTitle + extension);
    }

    /**
     * Import chapters already present in the configured media directory.
     * Scans both layouts so changing the website-subdirectory setting does not hide old downloads.
     */
    public async Import(manga: Manga, chapters: Chapter[]): Promise<void> {
        const settings = this.settingsManager.OpenScope(Scope);
        const root = settings.Get<Directory>(Key.MediaDirectory)?.Value;
        if (!root || await root.queryPermission({ mode: 'read' }) !== 'granted') return;

        const directories = await this.FindMangaDirectories(root, manga);
        for (const directory of directories) {
            const entries = new Map<string, FileSystemHandle>();
            for await (const entry of directory.handle.values()) {
                entries.set(entry.name.toLocaleLowerCase(), entry);
            }

            for (const chapter of chapters) {
                if (chapter.IsStored.Value) continue;
                const match = formats.find(candidate => {
                    const name = this.GetOutputName(chapter.Title, candidate.format).toLocaleLowerCase();
                    return entries.get(name)?.kind === candidate.kind;
                });
                if (!match) continue;

                const outputName = this.GetOutputName(chapter.Title, match.format);
                const relativePath = [ ...directory.path, outputName ].join('/');
                await this.MarkStored(chapter, match.format, relativePath, 'scan');
            }
        }
    }

    private async FindMangaDirectories(root: FileSystemDirectoryHandle, manga: Manga): Promise<ScanDirectory[]> {
        const result: ScanDirectory[] = [];
        const mangaName = SanitizeFileName(manga.Title);
        const websiteName = SanitizeFileName(manga.Parent?.Title ?? '');

        const candidates: ScanDirectory[] = [ { handle: root, path: [] } ];
        try {
            candidates.push({
                handle: await root.getDirectoryHandle(websiteName),
                path: [ websiteName ],
            });
        } catch { /* Website subdirectory is optional. */ }

        for (const candidate of candidates) {
            try {
                result.push({
                    handle: await candidate.handle.getDirectoryHandle(mangaName),
                    path: [ ...candidate.path, mangaName ],
                });
            } catch { /* Manga directory has not been downloaded in this layout. */ }
        }
        return result;
    }
}
