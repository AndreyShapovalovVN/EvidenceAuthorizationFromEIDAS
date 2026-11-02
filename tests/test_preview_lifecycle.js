const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {test} = require("node:test");
const {setImmediate: nextTurn} = require("node:timers/promises");
const {runInNewContext} = require("node:vm");

function createPage() {
    const listeners = {};
    const requests = [];
    let timeout;
    const window = {
        previewLifecycleConfig: {
            message_id: "msg-1", timeout_token: "token", wait_time: 600,
            returnurl: "https://example.com/back",
        },
        location: {},
        addEventListener: (name, callback) => { listeners[name] = callback; },
        dispatchEvent: (event) => { listeners[event.type]?.(); },
    };
    runInNewContext(readFileSync("static/preview_lifecycle.js", "utf8"), {
        window, Event, console,
        fetch: async (...args) => { requests.push(args); return {ok: true}; },
        setTimeout: (callback, delay) => {
            assert.equal(delay, 600000);
            timeout = callback;
            return 1;
        },
        clearTimeout: () => { timeout = undefined; },
    });
    return {window, listeners, requests, expire: () => timeout?.()};
}

test("closing an unfinished page sends an authenticated keepalive request once", async () => {
    const page = createPage();
    page.listeners.pagehide();
    page.listeners.pagehide();
    await nextTurn();
    assert.equal(page.requests.length, 1);
    assert.equal(page.requests[0][0], "/preview/timeout/msg-1?reason=closed");
    assert.equal(page.requests[0][1].headers["X-Action-Token"], "token");
    assert.equal(page.requests[0][1].keepalive, true);
    assert.equal(page.window.location.href, undefined);
});

test("timeout records the error and returns to caller without sending a close error", async () => {
    const page = createPage();
    page.expire();
    await nextTurn();
    assert.equal(page.requests[0][0], "/preview/timeout/msg-1?reason=timeout");
    assert.equal(page.window.location.href, "https://example.com/back");
    page.listeners.pagehide();
    assert.equal(page.requests.length, 1);
});

test("submission or internal navigation suppresses close and timeout errors", () => {
    const page = createPage();
    page.window.previewLifecycle.complete();
    page.listeners.pagehide();
    page.expire();
    assert.equal(page.requests.length, 0);
});
