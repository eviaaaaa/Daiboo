(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    }
    root.DaibooAppUtils = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    function createNdjsonParser(onEvent, onError) {
        let pending = '';
        const reportError = typeof onError === 'function' ? onError : function () {};

        function parseLine(line) {
            const trimmed = line.trim();
            if (!trimmed) return;
            try {
                onEvent(JSON.parse(trimmed));
            } catch (error) {
                reportError(error, line);
            }
        }

        return {
            push(chunk) {
                pending += String(chunk || '');
                const lines = pending.split('\n');
                pending = lines.pop() || '';
                lines.forEach(parseLine);
            },
            finish() {
                parseLine(pending);
                pending = '';
            }
        };
    }

    return { createNdjsonParser };
});
