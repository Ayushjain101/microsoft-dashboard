function timestamp() {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

const logger = {
  info: (msg) => console.log(`[${timestamp()}] INFO  ${msg}`),
  warn: (msg) => console.log(`[${timestamp()}] WARN  ${msg}`),
  error: (msg) => console.log(`[${timestamp()}] ERROR ${msg}`),
  success: (msg) => console.log(`[${timestamp()}] OK    ${msg}`),
};

module.exports = logger;
