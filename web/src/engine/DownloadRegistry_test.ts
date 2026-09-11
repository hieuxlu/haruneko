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
    } as unknown as StorageController;
    const settings = {
        OpenScope: vi.fn(() => ({
            Get: vi.fn(() => ({ Value: root })),
        })),
    } as unknown as SettingsManager;
    return { storage, settings, registry: new DownloadRegistry(storage, settings) };
}

describe('DownloadRegistry', () => {

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
