const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {test} = require("node:test");
const {runInNewContext} = require("node:vm");

function createPage(evidences) {
    const elements = new Map();
    function element(id) {
        if (!elements.has(id)) {
            elements.set(id, {
                style: {},
                classList: {toggle() {}},
                listeners: {},
                addEventListener(name, callback) { this.listeners[name] = callback; },
                removeAttribute(name) { delete this[name]; },
            });
        }
        return elements.get(id);
    }
    element("evidenceData").textContent = JSON.stringify(evidences);
    const buttons = evidences.map((evidence, index) => {
        const button = element(`select-${index}`);
        button.dataset = {evidenceIndex: String(index), defaultContentId: evidence.default_content_id};
        return button;
    });
    runInNewContext(readFileSync("static/evidences.js", "utf8"), {
        window: {addEventListener() {}},
        document: {
            getElementById: element,
            querySelectorAll: (selector) => selector === ".js-evidence-select" ? buttons : [],
        },
    });
    return {element, select: (index) => buttons[index].listeners.click()};
}

function evidence(title, contentType, content) {
    return {title, default_content_id: "doc", contents: [{id: "doc", content_type: contentType, content}]};
}

test("PDF download contains the selected document and follows evidence selection", () => {
    const first = Buffer.from("%PDF-1.7\nfirst").toString("base64");
    const second = Buffer.from("%PDF-1.7\nsecond").toString("base64");
    const page = createPage([
        evidence("Birth certificate", "application/pdf", first),
        evidence("Diploma.PDF", "application/pdf", second),
        evidence("Details", "application/xml", "<Root/>"),
    ]);
    const download = page.element("downloadPdf");
    assert.equal(download.hidden, false);
    assert.equal(download.download, "Birth certificate.pdf");
    assert.equal(download.href, `data:application/pdf;base64,${first}`);
    page.select(1);
    assert.equal(download.download, "Diploma.PDF");
    assert.equal(download.href, `data:application/pdf;base64,${second}`);
    page.select(2);
    assert.equal(download.hidden, true);
    assert.equal(download.href, undefined);
    page.select(0);
    assert.equal(download.hidden, false);
    assert.equal(download.href, `data:application/pdf;base64,${first}`);
});

test("empty PDF and other formats have no download link", () => {
    for (const [type, content] of [
        ["application/pdf", ""], ["application/pdf", null],
        ["application/pdf", "   "], ["application/json", '{"value":1}'],
    ]) {
        const page = createPage([evidence("Document", type, content)]);
        assert.equal(page.element("downloadPdf").hidden, true);
        assert.equal(page.element("downloadPdf").href, undefined);
    }
});

test("download filename removes filesystem separators and falls back to evidence", () => {
    const page = createPage([
        evidence("Folder/Name: certificate", "application/pdf", "JVBERg=="),
        evidence("", "application/pdf", "JVBERg=="),
    ]);
    assert.equal(page.element("downloadPdf").download, "Folder_Name_ certificate.pdf");
    page.select(1);
    assert.equal(page.element("downloadPdf").download, "evidence.pdf");
});
