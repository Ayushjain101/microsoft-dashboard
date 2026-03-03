/**
 * Google Apps Script for Selenium Tenant Setup Integration
 * ========================================================
 * Paste into: Extensions > Apps Script in your Google Sheet.
 * Creates a "Selenium" menu in the Sheet toolbar.
 */

// ── Configuration ───────────────────────────────────────────────────────────
var SERVER_URL = "http://15.204.175.41:8000";
var API_KEY = "Atoz12345"; // Must match the server's API_KEY env var

// ── Menu Setup ──────────────────────────────────────────────────────────────

function onOpen() {
  var ui = SpreadsheetApp.getUi();

  ui.createMenu("Selenium")
    .addItem("Run All Pending", "runAllPending")
    .addItem("Run Selected Rows", "runSelectedRows")
    .addSeparator()
    .addItem("Check Status", "checkStatus")
    .addItem("Stop Processing", "stopProcessing")
    .addSeparator()
    .addItem("Health Check", "healthCheck")
    .addToUi();

  ui.createMenu("Mailboxes")
    .addItem("Run All Pending", "mailboxRunAllPending")
    .addItem("Run Selected Rows", "mailboxRunSelectedRows")
    .addSeparator()
    .addItem("Check Status", "mailboxCheckStatus")
    .addItem("Stop Processing", "mailboxStopProcessing")
    .addToUi();
}

// ── Run All Pending ─────────────────────────────────────────────────────────

function runAllPending() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Settings");
  if (!sheet) {
    sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  }

  var data = sheet.getDataRange().getValues();
  var pending = [];

  // Find rows without "complete" in column H (index 7)
  for (var i = 1; i < data.length; i++) {
    var email = data[i][1]; // Column B
    var status = String(data[i][7]).toLowerCase(); // Column H
    if (email && status !== "complete") {
      pending.push(String(email).replace(/[\xa0]/g, '').trim());
    }
  }

  if (pending.length === 0) {
    ui.alert("No Pending Tenants", "All tenants already have 'complete' status.", ui.ButtonSet.OK);
    return;
  }

  var confirm = ui.alert(
    "Run Selenium Setup",
    "Found " + pending.length + " pending tenant(s):\n\n" + pending.join("\n") + "\n\nSend to server?",
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) return;

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/run", {
      method: "post",
      contentType: "application/json",
      headers: { "X-API-Key": API_KEY },
      payload: JSON.stringify({ emails: pending }),
      muteHttpExceptions: true,
    });

    var result = JSON.parse(response.getContentText());
    if (response.getResponseCode() === 200) {
      ui.alert("Queued", "Queued " + result.queued.length + " tenant(s).\nTotal in queue: " + result.total_in_queue, ui.ButtonSet.OK);
    } else {
      ui.alert("Error", "Server returned " + response.getResponseCode() + ":\n" + result.detail, ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Run Selected Rows ───────────────────────────────────────────────────────

function runSelectedRows() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var selection = sheet.getActiveRange();

  if (!selection) {
    ui.alert("No Selection", "Please select one or more rows first.", ui.ButtonSet.OK);
    return;
  }

  var emails = [];
  var startRow = selection.getRow();
  var numRows = selection.getNumRows();

  for (var i = 0; i < numRows; i++) {
    var email = sheet.getRange(startRow + i, 2).getValue(); // Column B
    if (email) {
      emails.push(String(email).replace(/[\xa0]/g, '').trim());
    }
  }

  if (emails.length === 0) {
    ui.alert("No Emails", "No emails found in column B of the selected rows.", ui.ButtonSet.OK);
    return;
  }

  var confirm = ui.alert(
    "Run Selected",
    "Send " + emails.length + " tenant(s) to server?\n\n" + emails.join("\n"),
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) return;

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/run", {
      method: "post",
      contentType: "application/json",
      headers: { "X-API-Key": API_KEY },
      payload: JSON.stringify({ emails: emails }),
      muteHttpExceptions: true,
    });

    var result = JSON.parse(response.getContentText());
    if (response.getResponseCode() === 200) {
      ui.alert("Queued", "Queued " + result.queued.length + " tenant(s).\nTotal in queue: " + result.total_in_queue, ui.ButtonSet.OK);
    } else {
      ui.alert("Error", "Server returned " + response.getResponseCode() + ":\n" + result.detail, ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Check Status ────────────────────────────────────────────────────────────

function checkStatus() {
  var ui = SpreadsheetApp.getUi();

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/status", {
      method: "get",
      headers: { "X-API-Key": API_KEY },
      muteHttpExceptions: true,
    });

    if (response.getResponseCode() !== 200) {
      ui.alert("Error", "Server returned " + response.getResponseCode(), ui.ButtonSet.OK);
      return;
    }

    var s = JSON.parse(response.getContentText());
    var msg = "";

    if (s.current_email) {
      msg += "Currently processing: " + s.current_email + "\n";
      msg += "Step: " + (s.current_step || "unknown") + "\n";
      msg += "Started: " + (s.started_at || "unknown") + "\n\n";
    } else {
      msg += "No tenant currently processing.\n\n";
    }

    msg += "Queue (" + s.queue_length + "): " + (s.queue.length > 0 ? s.queue.join(", ") : "(empty)") + "\n\n";

    if (s.completed.length > 0) {
      msg += "Completed (" + s.completed.length + "):\n";
      for (var i = 0; i < s.completed.length; i++) {
        var c = s.completed[i];
        msg += "  " + c.email + " — " + c.status;
        if (c.error) msg += " (" + c.error + ")";
        msg += "\n";
      }
    }

    ui.alert("Server Status", msg, ui.ButtonSet.OK);
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Stop Processing ─────────────────────────────────────────────────────────

function stopProcessing() {
  var ui = SpreadsheetApp.getUi();

  var confirm = ui.alert(
    "Stop Processing",
    "This will clear the queue. The current tenant will finish its setup.\n\nProceed?",
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) return;

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/stop", {
      method: "post",
      headers: { "X-API-Key": API_KEY },
      muteHttpExceptions: true,
    });

    var result = JSON.parse(response.getContentText());
    if (response.getResponseCode() === 200) {
      var msg = result.message + "\n";
      if (result.current_email) {
        msg += "\nCurrently finishing: " + result.current_email;
      }
      if (result.cleared_emails.length > 0) {
        msg += "\nCleared from queue: " + result.cleared_emails.join(", ");
      }
      ui.alert("Stop Requested", msg, ui.ButtonSet.OK);
    } else {
      ui.alert("Error", "Server returned " + response.getResponseCode(), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Health Check ────────────────────────────────────────────────────────────

function healthCheck() {
  var ui = SpreadsheetApp.getUi();

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/health", {
      method: "get",
      muteHttpExceptions: true,
    });

    if (response.getResponseCode() === 200) {
      var result = JSON.parse(response.getContentText());
      ui.alert("Server Online", "Server is running.\nTimestamp: " + result.timestamp, ui.ButtonSet.OK);
    } else {
      ui.alert("Server Error", "Server returned HTTP " + response.getResponseCode(), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Server Offline", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// Mailbox Functions
// ══════════════════════════════════════════════════════════════════════════════

// ── Mailbox: Run All Pending ───────────────────────────────────────────────

function mailboxRunAllPending() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Mailboxes");
  if (!sheet) {
    ui.alert("Missing Tab", "Could not find a 'Mailboxes' tab in this spreadsheet.", ui.ButtonSet.OK);
    return;
  }

  var data = sheet.getDataRange().getValues();
  var pending = [];

  // Find rows without "complete" or "running" in column G (index 6)
  for (var i = 1; i < data.length; i++) {
    var tenantName = data[i][1]; // Column B
    var status = String(data[i][6]).toLowerCase(); // Column G
    if (tenantName && status !== "complete" && status !== "running") {
      pending.push(String(tenantName).trim());
    }
  }

  if (pending.length === 0) {
    ui.alert("No Pending Tenants", "All tenants in the Mailboxes tab are already complete or running.", ui.ButtonSet.OK);
    return;
  }

  var confirm = ui.alert(
    "Create Mailboxes",
    "Found " + pending.length + " pending tenant(s):\n\n" + pending.join("\n") + "\n\nSend to server?",
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) return;

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/mailbox/run", {
      method: "post",
      contentType: "application/json",
      headers: { "X-API-Key": API_KEY },
      payload: JSON.stringify({ tenants: pending }),
      muteHttpExceptions: true,
    });

    var result = JSON.parse(response.getContentText());
    if (response.getResponseCode() === 200) {
      ui.alert("Queued", "Queued " + result.queued.length + " tenant(s) for mailbox creation.\nTotal in queue: " + result.total_in_queue, ui.ButtonSet.OK);
    } else {
      ui.alert("Error", "Server returned " + response.getResponseCode() + ":\n" + (result.detail || JSON.stringify(result)), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Mailbox: Run Selected Rows ─────────────────────────────────────────────

function mailboxRunSelectedRows() {
  var ui = SpreadsheetApp.getUi();
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var selection = sheet.getActiveRange();

  if (!selection) {
    ui.alert("No Selection", "Please select one or more rows first.", ui.ButtonSet.OK);
    return;
  }

  var tenants = [];
  var startRow = selection.getRow();
  var numRows = selection.getNumRows();

  for (var i = 0; i < numRows; i++) {
    var tenantName = sheet.getRange(startRow + i, 2).getValue(); // Column B
    if (tenantName) {
      tenants.push(String(tenantName).trim());
    }
  }

  if (tenants.length === 0) {
    ui.alert("No Tenants", "No tenant names found in column B of the selected rows.", ui.ButtonSet.OK);
    return;
  }

  var confirm = ui.alert(
    "Create Mailboxes",
    "Send " + tenants.length + " tenant(s) to server for mailbox creation?\n\n" + tenants.join("\n"),
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) return;

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/mailbox/run", {
      method: "post",
      contentType: "application/json",
      headers: { "X-API-Key": API_KEY },
      payload: JSON.stringify({ tenants: tenants }),
      muteHttpExceptions: true,
    });

    var result = JSON.parse(response.getContentText());
    if (response.getResponseCode() === 200) {
      ui.alert("Queued", "Queued " + result.queued.length + " tenant(s) for mailbox creation.\nTotal in queue: " + result.total_in_queue, ui.ButtonSet.OK);
    } else {
      ui.alert("Error", "Server returned " + response.getResponseCode() + ":\n" + (result.detail || JSON.stringify(result)), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Mailbox: Check Status ──────────────────────────────────────────────────

function mailboxCheckStatus() {
  var ui = SpreadsheetApp.getUi();

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/mailbox/status", {
      method: "get",
      headers: { "X-API-Key": API_KEY },
      muteHttpExceptions: true,
    });

    if (response.getResponseCode() !== 200) {
      ui.alert("Error", "Server returned " + response.getResponseCode(), ui.ButtonSet.OK);
      return;
    }

    var s = JSON.parse(response.getContentText());
    var msg = "";

    if (s.current_tenant) {
      msg += "Currently processing: " + s.current_tenant + "\n";
      msg += "Step: " + (s.current_step || "unknown") + "\n";
      msg += "Started: " + (s.started_at || "unknown") + "\n\n";
    } else {
      msg += "No tenant currently processing.\n\n";
    }

    msg += "Queue (" + s.queue_length + "): " + (s.queue.length > 0 ? s.queue.join(", ") : "(empty)") + "\n\n";

    if (s.completed.length > 0) {
      msg += "Completed (" + s.completed.length + "):\n";
      for (var i = 0; i < s.completed.length; i++) {
        var c = s.completed[i];
        msg += "  " + c.tenant + " — " + c.status;
        if (c.summary) msg += " (" + c.summary + ")";
        if (c.error) msg += " [ERROR: " + c.error + "]";
        msg += "\n";
      }
    }

    ui.alert("Mailbox Status", msg, ui.ButtonSet.OK);
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}

// ── Mailbox: Stop Processing ───────────────────────────────────────────────

function mailboxStopProcessing() {
  var ui = SpreadsheetApp.getUi();

  var confirm = ui.alert(
    "Stop Mailbox Processing",
    "This will clear the mailbox queue. The current tenant will finish its processing.\n\nProceed?",
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) return;

  try {
    var response = UrlFetchApp.fetch(SERVER_URL + "/api/mailbox/stop", {
      method: "post",
      headers: { "X-API-Key": API_KEY },
      muteHttpExceptions: true,
    });

    var result = JSON.parse(response.getContentText());
    if (response.getResponseCode() === 200) {
      var msg = result.message + "\n";
      if (result.current_tenant) {
        msg += "\nCurrently finishing: " + result.current_tenant;
      }
      if (result.cleared_tenants && result.cleared_tenants.length > 0) {
        msg += "\nCleared from queue: " + result.cleared_tenants.join(", ");
      }
      ui.alert("Stop Requested", msg, ui.ButtonSet.OK);
    } else {
      ui.alert("Error", "Server returned " + response.getResponseCode(), ui.ButtonSet.OK);
    }
  } catch (e) {
    ui.alert("Connection Error", "Could not reach server:\n" + e.message, ui.ButtonSet.OK);
  }
}
