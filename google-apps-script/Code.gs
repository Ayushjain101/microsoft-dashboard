// ── Google Apps Script for Microsoft 365 Tenant Pipeline ──────────────────
// Sheet ID: 1GKktibrC8gKYZQawPs_Cz9QWWad0Po8rkMVF9J_eP84

// ── MENU ──────────────────────────────────────────────────────────────────

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("🔧 Tenant Tools")
    .addItem("📋 Run Setup (create tabs + headers + buttons)", "runSetup")
    .addSeparator()
    .addSubMenu(
      SpreadsheetApp.getUi()
        .createMenu("Settings Tab")
        .addItem("Reset all statuses to pending", "resetSettingsStatuses")
        .addItem("Clear errors", "clearSettingsErrors")
    )
    .addSubMenu(
      SpreadsheetApp.getUi()
        .createMenu("Pipeline Tab")
        .addItem("Add tenant row", "addPipelineRow")
        .addItem("Reset all statuses to pending", "resetPipelineStatuses")
        .addItem("Clear errors", "clearPipelineErrors")
    )
    .addSeparator()
    .addItem("Format & style all tabs", "formatAllTabs")
    .addToUi();
}

// ── SETUP ─────────────────────────────────────────────────────────────────

function runSetup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ui = SpreadsheetApp.getUi();

  setupSettingsTab(ss);
  setupPipelineTab(ss);
  formatAllTabs();
  insertButtons(ss);

  ui.alert(
    "Setup Complete",
    "Both tabs are configured:\n\n" +
      "• Settings tab — columns A-J with status/error/completed_at\n" +
      "• Pipeline tab — columns A-H for API pipeline tracking\n" +
      "• Buttons added to both tabs\n\n" +
      "You can also use the 'Tenant Tools' menu above.",
    ui.ButtonSet.OK
  );
}

function setupSettingsTab(ss) {
  var ws;
  try {
    ws = ss.getSheetByName("Settings");
  } catch (e) {
    ws = null;
  }

  if (!ws) {
    ws = ss.insertSheet("Settings");
  }

  // Expected headers A-J
  var headers = [
    "tenant_name",
    "email",
    "password",
    "new_password",
    "tenant_id",
    "client_id",
    "client_secret",
    "status",
    "error",
    "completed_at",
  ];

  var currentHeaders = ws.getRange(1, 1, 1, ws.getMaxColumns()).getValues()[0];

  // Only update headers that are empty or missing
  for (var i = 0; i < headers.length; i++) {
    var col = i + 1;
    if (!currentHeaders[i] || currentHeaders[i] === "") {
      ws.getRange(1, col).setValue(headers[i]);
    }
  }

  // Set column widths
  var widths = [150, 280, 150, 150, 300, 300, 300, 90, 250, 180];
  for (var i = 0; i < widths.length; i++) {
    ws.setColumnWidth(i + 1, widths[i]);
  }

  // Add data validation for status column (H)
  var lastRow = Math.max(ws.getLastRow(), 50);
  var statusRange = ws.getRange(2, 8, lastRow - 1, 1);
  var statusRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(["pending", "running", "complete", "failed"], true)
    .setAllowInvalid(false)
    .build();
  statusRange.setDataValidation(statusRule);

  Logger.log("Settings tab configured");
}

function setupPipelineTab(ss) {
  var ws;
  try {
    ws = ss.getSheetByName("Pipeline");
  } catch (e) {
    ws = null;
  }

  if (!ws) {
    ws = ss.insertSheet("Pipeline");
  }

  var headers = [
    "tenant_name",
    "domain",
    "status",
    "current_step",
    "mailbox_count",
    "error",
    "started_at",
    "completed_at",
  ];

  // Write headers
  ws.getRange(1, 1, 1, headers.length).setValues([headers]);

  // Set column widths
  var widths = [150, 200, 90, 200, 120, 300, 180, 180];
  for (var i = 0; i < widths.length; i++) {
    ws.setColumnWidth(i + 1, widths[i]);
  }

  // Add data validation for status column (C)
  var lastRow = Math.max(ws.getLastRow(), 50);
  var statusRange = ws.getRange(2, 3, lastRow - 1, 1);
  var statusRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(["pending", "running", "done", "failed"], true)
    .setAllowInvalid(false)
    .build();
  statusRange.setDataValidation(statusRule);

  // Default mailbox_count to 50 for empty cells
  var mbRange = ws.getRange(2, 5, lastRow - 1, 1);
  // Just set a note as reminder
  ws.getRange(1, 5).setNote("Default: 50 if left blank");

  Logger.log("Pipeline tab configured");
}

// ── BUTTONS ───────────────────────────────────────────────────────────────

function insertButtons(ss) {
  // Settings tab buttons
  var settings = ss.getSheetByName("Settings");
  if (settings) {
    // Put button labels in column L
    settings.getRange("L1").setValue("ACTIONS").setFontWeight("bold");
    settings
      .getRange("L2")
      .setValue("▶ Reset All to Pending")
      .setBackground("#4CAF50")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    settings
      .getRange("L3")
      .setValue("🗑 Clear All Errors")
      .setBackground("#FF9800")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    settings
      .getRange("L4")
      .setValue("🔄 Run Setup Again")
      .setBackground("#2196F3")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    settings.setColumnWidth(12, 200);

    // Add a note explaining how to use
    settings
      .getRange("L1")
      .setNote(
        "These are visual labels. Use the Tenant Tools menu at the top to run actions."
      );
  }

  // Pipeline tab buttons
  var pipeline = ss.getSheetByName("Pipeline");
  if (pipeline) {
    pipeline.getRange("J1").setValue("ACTIONS").setFontWeight("bold");
    pipeline
      .getRange("J2")
      .setValue("▶ Reset All to Pending")
      .setBackground("#4CAF50")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    pipeline
      .getRange("J3")
      .setValue("➕ Add Tenant Row")
      .setBackground("#9C27B0")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    pipeline
      .getRange("J4")
      .setValue("🗑 Clear All Errors")
      .setBackground("#FF9800")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    pipeline
      .getRange("J5")
      .setValue("🔄 Run Setup Again")
      .setBackground("#2196F3")
      .setFontColor("white")
      .setFontWeight("bold")
      .setHorizontalAlignment("center");
    pipeline.setColumnWidth(10, 200);

    pipeline
      .getRange("J1")
      .setNote(
        "These are visual labels. Use the Tenant Tools menu at the top to run actions."
      );
  }
}

// ── FORMATTING ────────────────────────────────────────────────────────────

function formatAllTabs() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // Format Settings tab
  var settings = ss.getSheetByName("Settings");
  if (settings) {
    formatHeader(settings, 10);
    addConditionalFormatting(settings, 8); // Status in column H
  }

  // Format Pipeline tab
  var pipeline = ss.getSheetByName("Pipeline");
  if (pipeline) {
    formatHeader(pipeline, 8);
    addConditionalFormatting(pipeline, 3); // Status in column C
  }
}

function formatHeader(sheet, numCols) {
  var headerRange = sheet.getRange(1, 1, 1, numCols);
  headerRange
    .setBackground("#1a73e8")
    .setFontColor("white")
    .setFontWeight("bold")
    .setHorizontalAlignment("center");

  // Freeze header row
  sheet.setFrozenRows(1);
}

function addConditionalFormatting(sheet, statusCol) {
  // Clear existing conditional format rules
  sheet.clearConditionalFormatRules();

  var lastRow = Math.max(sheet.getLastRow(), 100);
  var range = sheet.getRange(2, statusCol, lastRow - 1, 1);

  var rules = [];

  // pending = light gray
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo("pending")
      .setBackground("#E0E0E0")
      .setFontColor("#616161")
      .setRanges([range])
      .build()
  );

  // running = light blue
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo("running")
      .setBackground("#BBDEFB")
      .setFontColor("#1565C0")
      .setRanges([range])
      .build()
  );

  // complete/done = light green
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo("complete")
      .setBackground("#C8E6C9")
      .setFontColor("#2E7D32")
      .setRanges([range])
      .build()
  );
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo("done")
      .setBackground("#C8E6C9")
      .setFontColor("#2E7D32")
      .setRanges([range])
      .build()
  );

  // failed = light red
  rules.push(
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo("failed")
      .setBackground("#FFCDD2")
      .setFontColor("#C62828")
      .setRanges([range])
      .build()
  );

  sheet.setConditionalFormatRules(rules);
}

// ── ACTIONS ───────────────────────────────────────────────────────────────

function resetSettingsStatuses() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName("Settings");
  if (!ws) return;

  var lastRow = ws.getLastRow();
  if (lastRow < 2) return;

  // Set all status cells (H) to "pending", clear error (I) and completed_at (J)
  for (var r = 2; r <= lastRow; r++) {
    if (ws.getRange(r, 1).getValue() !== "") {
      ws.getRange(r, 8).setValue("pending");
      ws.getRange(r, 9).setValue("");
      ws.getRange(r, 10).setValue("");
    }
  }

  SpreadsheetApp.getUi().alert("All Settings statuses reset to pending.");
}

function clearSettingsErrors() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName("Settings");
  if (!ws) return;

  var lastRow = ws.getLastRow();
  if (lastRow < 2) return;

  ws.getRange(2, 9, lastRow - 1, 1).setValue(""); // Clear error column
  SpreadsheetApp.getUi().alert("Settings errors cleared.");
}

function resetPipelineStatuses() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName("Pipeline");
  if (!ws) return;

  var lastRow = ws.getLastRow();
  if (lastRow < 2) return;

  for (var r = 2; r <= lastRow; r++) {
    if (ws.getRange(r, 1).getValue() !== "") {
      ws.getRange(r, 3).setValue("pending");
      ws.getRange(r, 4).setValue("");
      ws.getRange(r, 6).setValue("");
      ws.getRange(r, 7).setValue("");
      ws.getRange(r, 8).setValue("");
    }
  }

  SpreadsheetApp.getUi().alert("All Pipeline statuses reset to pending.");
}

function clearPipelineErrors() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ws = ss.getSheetByName("Pipeline");
  if (!ws) return;

  var lastRow = ws.getLastRow();
  if (lastRow < 2) return;

  ws.getRange(2, 6, lastRow - 1, 1).setValue(""); // Clear error column
  SpreadsheetApp.getUi().alert("Pipeline errors cleared.");
}

function addPipelineRow() {
  var ui = SpreadsheetApp.getUi();

  var tenantResp = ui.prompt(
    "Add Tenant to Pipeline",
    "Enter tenant name:",
    ui.ButtonSet.OK_CANCEL
  );
  if (tenantResp.getSelectedButton() !== ui.Button.OK) return;

  var domainResp = ui.prompt(
    "Add Tenant to Pipeline",
    "Enter domain (e.g. example.com):",
    ui.ButtonSet.OK_CANCEL
  );
  if (domainResp.getSelectedButton() !== ui.Button.OK) return;

  var countResp = ui.prompt(
    "Add Tenant to Pipeline",
    "Number of mailboxes (default 50):",
    ui.ButtonSet.OK_CANCEL
  );
  if (countResp.getSelectedButton() !== ui.Button.OK) return;

  var tenant = tenantResp.getResponseText().trim();
  var domain = domainResp.getResponseText().trim();
  var count = countResp.getResponseText().trim() || "50";

  if (!tenant) {
    ui.alert("Tenant name is required.");
    return;
  }

  var ws = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("Pipeline");
  if (!ws) {
    ui.alert("Pipeline tab not found. Run Setup first.");
    return;
  }

  var newRow = ws.getLastRow() + 1;
  ws.getRange(newRow, 1).setValue(tenant);
  ws.getRange(newRow, 2).setValue(domain);
  ws.getRange(newRow, 3).setValue("pending");
  ws.getRange(newRow, 5).setValue(count);

  ui.alert("Added: " + tenant + " (" + domain + ") with " + count + " mailboxes.");
}
