(function () {
    const config = window.previewLifecycleConfig;
    let finished = false;
    let timer;

    function complete() {
        finished = true;
        clearTimeout(timer);
    }

    async function terminate(reason) {
        if (finished) {
            return;
        }
        complete();
        window.dispatchEvent(new Event("preview-ended"));
        try {
            await fetch(`/preview/timeout/${config.message_id}?reason=${reason}`, {
                method: "POST",
                headers: {"X-Action-Token": config.timeout_token},
                keepalive: true,
            });
        } catch (error) {
            console.error("Failed to record preview termination:", error);
        }
        if (reason === "timeout" && config.returnurl) {
            window.location.href = config.returnurl;
        }
    }

    window.previewLifecycle = {complete, isFinished: () => finished};
    window.addEventListener("pagehide", () => { void terminate("closed"); });
    timer = setTimeout(() => { void terminate("timeout"); }, config.wait_time * 1000);
})();
