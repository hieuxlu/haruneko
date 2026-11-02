import { describe, expect, it, vi } from 'vitest';
import { DownloadRegistry, type DownloadRecord } from './DownloadRegistry';
import { MangaExportFormat } from './exporters/MangaExporterRegistry';
import { Store, type StorageController } from './StorageController';
import type { SettingsManager } from './SettingsManager';
import type { Chapter, Manga } from './providers/MangaPlugin';

type MockHandle = {
    name: string;
    kind: 'file' | 'directory';
    children?: Map<string, MockHandle>;
    queryPermission?: () => Promise<PermissionState>;
    getDirectoryHandle?: (name: string) => Promise<MockHandle>;
    values?: () => AsyncGenerator<MockHandle>;
};

function File(name: string): MockHandle {
    return { name, kind: 'file' };
}

function Directory(name: string, entries: MockHandle[] = [], permission: PermissionState = 'granted'): MockHandle {
    const children = new Map(entries.map(entry => [ entry.name, entry ]));
    return {
        name,
        kind: 'directory',
        children,
        queryPermission: async () => permission,
        getDirectoryHandle: async childName => {
            const child = children.get(childName);
            if (child?.kind !== 'directory') throw new DOMException('Not found', 'NotFoundError');
            return child;
        },
        async *values() {
            yield* children.values();
        },
    };
}

function Media() {
    const website = { Identifier: 'viz', Title: 'Viz - Shonen Jump' };
    const manga = {
        Identifier: '/frieren',
        Title: 'Frieren: Beyond Journey’s End',
        Parent: website,
    } as Manga;
    const chapter = {
        Identifier: '/chapter/68',
        Title: 'Chapter 68',
        Parent: manga,
        IsStored: { Value: false },
        IsManuallyDownloaded: { Value: false },
        SetManuallyDownloaded: vi.fn(function (this: typeof chapter, value: boolean) {
            this.IsManuallyDownloaded.Value = value;
        }),
        SetStored: vi.fn(function (this: typeof chapter, value: boolean) {
            this.IsStored.Value = value;
        }),
    } as unknown as Chapter;
    return { manga, chapter };
}

function Fixture(root: MockHandle, records: DownloadRecord[] = []) {
    const storage = {
        LoadPersistent: vi.fn().mockResolvedValue(records),
        SavePersistent: vi.fn().mockResolvedValue(undefined),
        RemovePersistent: vi.fn().mockResolvedValue(undefined),
    } as unknown as StorageController;
    const settings = {
        OpenScope: vi.fn(() => ({
            Get: vi.fn(() => ({ Value: root })),
        })),
    } as unknown as SettingsManager;
    return { storage, settings, registry: new DownloadRegistry(storage, settings) };
}

describe('DownloadRegistry', () => {

    it('Should persist a manual download without a directory or local output', async () => {
        const { chapter } = Media();
        const fixture = Fixture(undefined);

        await fixture.registry.SetDownloaded(chapter, true);

        const record = await fixture.registry.GetRecord(chapter);
        expect(record.source).toBe('manual');
        expect(record.relativePath).toBeUndefined();
        expect(record.format).toBeUndefined();
        expect(chapter.IsManuallyDownloaded.Value).toBe(true);
        await expect(fixture.registry.IsStored(chapter)).resolves.toBe(false);
        expect(fixture.settings.OpenScope).not.toHaveBeenCalled();

        const reloaded = Fixture(undefined, [record]);
        await expect(reloaded.registry.GetRecord(Media().chapter)).resolves.toEqual(record);
    });

    it('Should clear a manual download so it becomes missing again', async () => {
        const { chapter } = Media();
        const fixture = Fixture(undefined);
        await fixture.registry.SetDownloaded(chapter, true);

        await fixture.registry.SetDownloaded(chapter, false);

        expect(fixture.storage.RemovePersistent).toHaveBeenCalledWith(Store.Downloads, DownloadRegistry.GetKey(chapter));
        expect(chapter.IsManuallyDownloaded.Value).toBe(false);
        await expect(fixture.registry.GetRecord(chapter)).resolves.toBeUndefined();
    });

    it('Should retain other selected chapters when clearing one manual mark', async () => {
        const first = Media().chapter;
        const second = Media().chapter;
        Object.defineProperty(second, 'Identifier', { value: '/chapter/69' });
        const fixture = Fixture(undefined);

        for (const chapter of [first, second]) {
            await fixture.registry.SetDownloaded(chapter, true);
        }
        await fixture.registry.SetDownloaded(first, false);

        await expect(fixture.registry.GetRecord(first)).resolves.toBeUndefined();
        expect((await fixture.registry.GetRecord(second)).source).toBe('manual');
        expect(second.IsManuallyDownloaded.Value).toBe(true);
    });

    it('Should preserve manual status when saving or clearing it fails', async () => {
        const { chapter } = Media();
        const fixture = Fixture(undefined);
        vi.mocked(fixture.storage.SavePersistent).mockRejectedValueOnce(new Error('Save failed'));
        await expect(fixture.registry.SetDownloaded(chapter, true)).rejects.toThrow('Save failed');
        expect(chapter.IsManuallyDownloaded.Value).toBe(false);
        await expect(fixture.registry.GetRecord(chapter)).resolves.toBeUndefined();

        await fixture.registry.SetDownloaded(chapter, true);
        vi.mocked(fixture.storage.RemovePersistent).mockRejectedValueOnce(new Error('Remove failed'));
        await expect(fixture.registry.SetDownloaded(chapter, false)).rejects.toThrow('Remove failed');
        expect(chapter.IsManuallyDownloaded.Value).toBe(true);
        expect((await fixture.registry.GetRecord(chapter)).source).toBe('manual');
    });

    it('Should preserve local output details when manually marking a stored chapter', async () => {
        const { chapter } = Media();
        const fixture = Fixture(undefined);
        await fixture.registry.MarkStored(chapter, MangaExportFormat.CBZ, 'Frieren/Chapter 68.cbz');

        await fixture.registry.SetDownloaded(chapter, true);

        expect((await fixture.registry.GetRecord(chapter)).source).toBe('download');
        expect(chapter.IsStored.Value).toBe(true);
        expect(chapter.IsManuallyDownloaded.Value).toBe(false);
        expect(fixture.storage.SavePersistent).toHaveBeenCalledTimes(1);
    });

    it('Should replace a manual mark when a local chapter is discovered', async () => {
        const { manga, chapter } = Media();
        const fixture = Fixture(Directory('Media', [
            Directory('Frieren꞉ Beyond Journey’s End', [File('Chapter 68.cbz')]),
        ]));
        await fixture.registry.SetDownloaded(chapter, true);

        await fixture.registry.Import(manga, [chapter]);

        expect((await fixture.registry.GetRecord(chapter)).source).toBe('scan');
        expect(chapter.IsManuallyDownloaded.Value).toBe(false);
        expect(chapter.IsStored.Value).toBe(true);
    });

    it('Should persist a stable chapter record after a successful download', async () => {
        const { chapter } = Media();
        const fixture = Fixture(Directory('Media'));

        await fixture.registry.MarkStored(chapter, MangaExportFormat.CBZ, 'Frieren/Chapter 68.cbz');

        expect(fixture.storage.SavePersistent).toHaveBeenCalledWith(
            expect.objectContaining({
                key: JSON.stringify([ 'viz', '/frieren', '/chapter/68' ]),
                format: MangaExportFormat.CBZ,
                relativePath: 'Frieren/Chapter 68.cbz',
                source: 'download',
            }),
            Store.Downloads,
            JSON.stringify([ 'viz', '/frieren', '/chapter/68' ]),
        );
        expect(chapter.SetStored).toHaveBeenCalledWith(true);
    });

    it('Should not mark a chapter as stored when persisting the record fails', async () => {
        const { chapter } = Media();
        const fixture = Fixture(Directory('Media'));
        vi.mocked(fixture.storage.SavePersistent).mockRejectedValueOnce(new Error('Storage failed'));

        await expect(fixture.registry.MarkStored(chapter, MangaExportFormat.CBZ, 'Frieren/Chapter 68.cbz'))
            .rejects.toThrow('Storage failed');

        expect(chapter.SetStored).not.toHaveBeenCalled();
        await expect(fixture.registry.IsStored(chapter)).resolves.toBe(false);
    });

    it('Should import an existing CBZ from the media directory', async () => {
        const { manga, chapter } = Media();
        const mangaDirectory = Directory('Frieren꞉ Beyond Journey’s End', [ File('Chapter 68.cbz') ]);
        const fixture = Fixture(Directory('Media', [ mangaDirectory ]));

        await fixture.registry.Import(manga, [ chapter ]);

        expect(fixture.storage.SavePersistent).toHaveBeenCalledWith(
            expect.objectContaining({
                format: MangaExportFormat.CBZ,
                relativePath: 'Frieren꞉ Beyond Journey’s End/Chapter 68.cbz',
                source: 'scan',
            }),
            Store.Downloads,
            expect.any(String),
        );
        expect(chapter.SetStored).toHaveBeenCalledWith(true);
    });

    it('Should not scan when the persisted directory permission is unavailable', async () => {
        const { manga, chapter } = Media();
        const fixture = Fixture(Directory('Media', [], 'prompt'));

        await fixture.registry.Import(manga, [ chapter ]);

        expect(fixture.storage.SavePersistent).not.toHaveBeenCalled();
        expect(chapter.SetStored).not.toHaveBeenCalled();
    });
});
