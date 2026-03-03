const { getStatus } = require("./sheets");
const log = require("./logger");

const POLL_INTERVAL = 15_000; // 15 seconds
const TIMEOUT = 3_600_000;    // 1 hour

function waitForStart() {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + TIMEOUT;

    async function poll() {
      try {
        const data = await getStatus();
        const pendingCount = (data.pending || []).length;
        log.info(`Sheet status: ${data.status} | ${pendingCount} pending row(s)`);

        if (data.status === "START") {
          resolve(data);
          return;
        }
      } catch (err) {
        log.warn(`Poll error: ${err.message}`);
      }

      if (Date.now() > deadline) {
        reject(new Error("Polling timed out after 1 hour"));
        return;
      }

      setTimeout(poll, POLL_INTERVAL);
    }

    log.info("Polling for START signal every 15s (1h timeout)...");
    poll();
  });
}

module.exports = { waitForStart };
