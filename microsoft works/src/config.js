const path = require("path");
require("dotenv").config({ path: path.join(__dirname, "..", ".env") });

const REQUIRED = ["APPS_SCRIPT_URL"];

const missing = REQUIRED.filter((key) => !process.env[key] || process.env[key].startsWith("your-"));
if (missing.length > 0) {
  console.error(`Missing or placeholder .env variables: ${missing.join(", ")}`);
  process.exit(1);
}

module.exports = {
  appsScriptUrl: process.env.APPS_SCRIPT_URL,
};
