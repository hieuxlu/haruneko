import puppeteer from 'puppeteer-core';

const chapterURL = process.argv.at(2) ?? 'https://www.viz.com/vizmanga/frieren-the-journeys-end-chapter-68/chapter/39572?action=read';
const browser = await puppeteer.connect({ browserURL: 'http://127.0.0.1:9222' });

const channels = {
    open: 'RemoteBrowserWindowController::OpenWindow',
    close: 'RemoteBrowserWindowController::CloseWindow',
    execute: 'RemoteBrowserWindowController::ExecuteScript',
    debug: 'RemoteBrowserWindowController::SendDebugCommand',
    load: 'RemoteBrowserWindowController::LoadURL',
};

const openOptions = {
    show: false,
    width: 1280,
    height: 800,
    center: true,
    webPreferences: {
        sandbox: true,
        webSecurity: true,
        contextIsolation: false,
        nodeIntegration: false,
        nodeIntegrationInWorker: false,
        nodeIntegrationInSubFrames: true,
        backgroundThrottling: false,
        disableBlinkFeatures: 'AutomationControlled',
    },
};

let hostPage;
let windowID;

try {
    const pages = await browser.pages();
    hostPage = pages.find(page => /^https:\/\/127\.0\.0\.1:5000(?:\/|$)/.test(page.url()))
        ?? pages.find(page => typeof page.url() === 'string' && !page.url().startsWith('devtools:'));

    if (!hostPage) {
        throw new Error(`Could not find HakuNeko's renderer. CDP targets: ${pages.map(page => page.url()).join(', ')}`);
    }

    const hasIPC = await hostPage.evaluate(() => typeof globalThis.ipcRenderer?.invoke === 'function');
    if (!hasIPC) {
        throw new Error(`The selected CDP target does not expose HakuNeko IPC: ${hostPage.url()}`);
    }

    windowID = await hostPage.evaluate(
        ({ channel, options }) => globalThis.ipcRenderer.invoke(channel, JSON.stringify(options)),
        { channel: channels.open, options: openOptions },
    );

    await hostPage.evaluate(
        ({ channel, id, url, options }) => globalThis.ipcRenderer.invoke(channel, id, url, JSON.stringify(options)),
        { channel: channels.load, id: windowID, url: chapterURL, options: { userAgent: await browser.userAgent() } },
    );

    await new Promise(resolve => setTimeout(resolve, 2_000));

    const script = String.raw`(async () => {
        const getGlobal = name => {
            try {
                return globalThis[name] ?? globalThis.eval('typeof ' + name + " === 'undefined' ? undefined : " + name);
            } catch {
                return undefined;
            }
        };

        const mangaID = getGlobal('mangaCommonId') ?? getGlobal('currentMCid');
        const pagesCount = getGlobal('pages');
        let auth = null;
        let api = null;
        if (mangaID !== undefined && mangaID !== null) {
            const authEndpoint = new URL('/manga/auth', location.origin);
            authEndpoint.searchParams.set('device_id', '3');
            authEndpoint.searchParams.set('manga_id', String(mangaID));
            const authResponse = await fetch(authEndpoint, { credentials: 'include' });
            auth = {
                status: authResponse.status,
                body: (await authResponse.text()).slice(0, 500),
            };

            const endpoint = new URL('/manga/get_manga_url', location.origin);
            endpoint.searchParams.set('device_id', '3');
            endpoint.searchParams.set('manga_id', String(mangaID));
            endpoint.searchParams.set('pages', Array.from({ length: Number(pagesCount) + 1 }, (_, index) => index).join(','));
            const response = await fetch(endpoint, { credentials: 'include' });
            const body = await response.json();
            api = {
                url: endpoint.href,
                status: response.status,
                ok: body.ok ?? null,
                dataType: typeof body.data,
                pageKeys: typeof body.data === 'object' && body.data ? Object.keys(body.data) : [],
                error: typeof body.data === 'string' ? body.data : null,
            };
        }

        return {
            finalURL: location.href,
            title: document.title,
            userID: getGlobal('user_id') ?? null,
            isVizMangaSubscriber: getGlobal('is_vm_subscriber') ?? null,
            isShonenJumpSubscriber: getGlobal('is_sj_subscriber') ?? null,
            mangaID: mangaID ?? null,
            pagesCount: pagesCount ?? null,
            documentCookieNames: document.cookie.split(';').map(part => part.split('=', 1)[0].trim()).filter(Boolean),
            auth,
            api,
        };
    })()`;

    const state = await hostPage.evaluate(
        ({ channel, id, code }) => globalThis.ipcRenderer.invoke(channel, id, code),
        { channel: channels.execute, id: windowID, code: script },
    );

    const cookieResult = await hostPage.evaluate(
        ({ channel, id, urls }) => globalThis.ipcRenderer.invoke(channel, id, 'Network.getCookies', { urls }),
        { channel: channels.debug, id: windowID, urls: [ chapterURL, 'https://www.viz.com/manga/get_manga_url' ] },
    );

    const report = {
        chapterURL,
        hostRenderer: hostPage.url(),
        state,
        cookies: (cookieResult.cookies ?? []).map(cookie => ({
            name: cookie.name,
            domain: cookie.domain,
            path: cookie.path,
            secure: cookie.secure,
            httpOnly: cookie.httpOnly,
            sameSite: cookie.sameSite,
            expires: cookie.expires,
            partitionKey: cookie.partitionKey,
        })),
    };
    console.log(JSON.stringify(report, null, 2));
} finally {
    if (hostPage && windowID !== undefined) {
        await hostPage.evaluate(
            ({ channel, id }) => globalThis.ipcRenderer.invoke(channel, id),
            { channel: channels.close, id: windowID },
        ).catch(() => {});
    }
    browser.disconnect();
}
