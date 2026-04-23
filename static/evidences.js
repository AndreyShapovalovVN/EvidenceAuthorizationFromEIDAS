(function () {
    const dataNode = document.getElementById("evidenceData");
    if (!dataNode) {
        return;
    }
    const evidences = JSON.parse(dataNode.textContent || "[]");
    const pageConfig = window.evidencePageConfig || {};
    const evidenceItems = Array.from(document.querySelectorAll(".js-evidence-item"));
    const evidenceButtons = Array.from(document.querySelectorAll(".js-evidence-select"));
    const contentButtons = Array.from(document.querySelectorAll(".js-content-select"));
    const viewAllButtons = Array.from(document.querySelectorAll(".js-view-all"));
    const pdfViewer = document.getElementById("pdfViewer");
    const textViewer = document.getElementById("textViewer");
    const emptyViewer = document.getElementById("emptyViewer");
    const viewerMeta = document.getElementById("viewerMeta");
    const submitBtn = document.getElementById("submitBtn");
    const resultMessage = document.getElementById("resultMessage");
    let activeEvidenceIndex = 0;
    let activeContentId = "";
    function findEvidence(index) {
        const value = evidences[index];
        if (!value || !Array.isArray(value.contents)) {
            return null;
        }
        return value;
    }
    function findContent(evidence, contentId) {
        return evidence.contents.find((item) => item.id === contentId) || null;
    }
    function formatContent(rawContent) {
        if (typeof rawContent === "string") {
            return rawContent;
        }
        try {
            return JSON.stringify(rawContent, null, 2);
        } catch (_error) {
            return String(rawContent);
        }
    }
    function setViewerState(content) {
        const isPdf = content.content_type === "application/pdf" && typeof content.content === "string";
        const cid = content.cid ? `CID: ${content.cid}` : "CID: n/a";
        const type = content.content_type || "unknown";
        const node = content.classification_node || "Unknown";
        viewerMeta.textContent = `${node} | ${type} | ${cid}`;
        if (isPdf) {
            pdfViewer.src = `data:application/pdf;base64,${content.content}`;
            pdfViewer.style.display = "block";
            textViewer.style.display = "none";
            emptyViewer.style.display = "none";
            return;
        }
        const hasContent = content.content !== null && content.content !== undefined && content.content !== "";
        if (hasContent) {
            textViewer.textContent = formatContent(content.content);
            textViewer.style.display = "block";
            pdfViewer.style.display = "none";
            emptyViewer.style.display = "none";
            return;
        }
        emptyViewer.textContent = "No content available for selected item.";
        emptyViewer.style.display = "block";
        pdfViewer.style.display = "none";
        textViewer.style.display = "none";
    }
    function refreshActiveButtons() {
        evidenceItems.forEach((item, idx) => {
            item.classList.toggle("active", idx === activeEvidenceIndex);
        });
        contentButtons.forEach((button) => {
            const selected =
                Number(button.dataset.evidenceIndex) === activeEvidenceIndex &&
                button.dataset.contentId === activeContentId;
            button.classList.toggle("active", selected);
        });
        viewAllButtons.forEach((button) => {
            const selected =
                Number(button.dataset.evidenceIndex) === activeEvidenceIndex &&
                activeContentId === "all-contents";
            button.classList.toggle("active", selected);
        });
    }
    function selectContent(evidenceIndex, contentId) {
        const evidence = findEvidence(evidenceIndex);
        if (!evidence) {
            return;
        }
        const content = findContent(evidence, contentId) || evidence.contents[0];
        if (!content) {
            return;
        }
        activeEvidenceIndex = evidenceIndex;
        activeContentId = content.id;
        refreshActiveButtons();
        setViewerState(content);
    }
    evidenceButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const evidenceIndex = Number(button.dataset.evidenceIndex || "0");
            const defaultContentId = button.dataset.defaultContentId || "";
            selectContent(evidenceIndex, defaultContentId);
        });
    });
    contentButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const evidenceIndex = Number(button.dataset.evidenceIndex || "0");
            const contentId = button.dataset.contentId || "";
            selectContent(evidenceIndex, contentId);
        });
    });
    viewAllButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const evidenceIndex = Number(button.dataset.evidenceIndex || "0");
            const evidence = findEvidence(evidenceIndex);
            if (!evidence) {
                return;
            }
            // Show consolidated view of all contents
            // Create a combined text view
            const allContent = evidence.contents
                .filter(c => c.content !== null && c.content !== undefined)
                .map(c => `\n=== ${c.label} ===\nType: ${c.content_type}\nCID: ${c.cid}\n\n${formatContent(c.content)}`)
                .join("\n\n");
            activeEvidenceIndex = evidenceIndex;
            activeContentId = "all-contents";
            refreshActiveButtons();
            textViewer.textContent = allContent || "No content available for any items.";
            textViewer.style.display = "block";
            pdfViewer.style.display = "none";
            emptyViewer.style.display = "none";
            viewerMeta.textContent = `All Contents | ${evidence.contents.length} items`;
        });
    });
    submitBtn.addEventListener("click", async function () {
        const checkboxes = Array.from(document.querySelectorAll(".js-permit-checkbox"));
        const approvals = {};
        checkboxes.forEach((checkbox) => {
            const key = checkbox.dataset.approvalKey;
            if (!key) {
                return;
            }
            approvals[key] = Boolean(checkbox.checked);
        });
        try {
            const response = await fetch("/preview/continue", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message_uuid: pageConfig.message_uuid,
                    approvals: approvals
                })
            });
            const payload = await response.json();
            if (!response.ok) {
                throw new Error(payload.detail || "Failed to submit approvals");
            }
            resultMessage.textContent = `OK: ${payload.message}`;
            resultMessage.className = "result-message ok";
            if (pageConfig.returnurl) {
                window.location.href = pageConfig.returnurl;
            }
        } catch (error) {
            resultMessage.textContent = `Error: ${error.message || "Failed to submit approvals"}`;
            resultMessage.className = "result-message err";
        }
    });
    const firstEvidence = findEvidence(0);
    if (firstEvidence) {
        selectContent(0, firstEvidence.default_content_id || "");
    }
})();
