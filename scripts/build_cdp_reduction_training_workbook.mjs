import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = process.cwd();
const inputPath = `${root}/data/processed/cdp_section_datasets/reduction_training_round_2.json`;
const outputPath = `${root}/data/processed/cdp_section_datasets/cdp_reduction_training_round_2.xlsx`;
const payload = JSON.parse(await fs.readFile(inputPath, "utf8"));

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("Instructions");
const coding = workbook.worksheets.add("Reduction actions");
const lists = workbook.worksheets.add("Coding lists");

instructions.getRange("A1:H1").merge();
instructions.getRange("A1").values = [[payload.title]];
instructions.getRange("A1:H1").format = {
  font: { name: "Arial", size: 15, bold: true, color: "#1F1F1F" },
  verticalAlignment: "center",
};
instructions.getRange("A3").values = [["Purpose"]];
instructions.getRange("B3:H3").merge();
instructions.getRange("B3").values = [["Add human labels to a balanced sample of CDP reduction initiatives from 2020–2022. The completed rows will expand the supervised training data."]];
instructions.getRange("A5").values = [["Coding steps"]];
payload.instructions.forEach((line, index) => {
  instructions.getRange(`A${6 + index}`).values = [[index + 1]];
  instructions.getRange(`B${6 + index}:H${6 + index}`).merge();
  instructions.getRange(`B${6 + index}`).values = [[line]];
});
instructions.getRange("A3:A10").format.font = { name: "Arial", bold: true, color: "#1F4E78" };
instructions.getRange("A1:H10").format.wrapText = true;
instructions.getRange("A1:H10").format.verticalAlignment = "top";
instructions.getRange("A:A").format.columnWidth = 15;
instructions.getRange("B:H").format.columnWidth = 18;
instructions.getRange("B3:H10").format.rowHeight = 32;
instructions.showGridLines = false;

const columns = payload.columns;
coding.getRange("A1:S1").merge();
coding.getRange("A1").values = [["Reduction actions"]];
coding.getRange("A2:S2").merge();
coding.getRange("A2").values = [["One row per CDP initiative. Complete the coding fields using the same definitions as the original validation workbook."]];
coding.getRange("A3:S3").values = [columns];
const body = payload.rows.map(row => columns.map(column => row[column] ?? ""));
coding.getRange(`A4:S${body.length + 3}`).values = body;
coding.getRange("A1:S1").format = { font: { name: "Arial", size: 14, bold: true, color: "#1F1F1F" } };
coding.getRange("A2:S2").format = { font: { name: "Arial", size: 10, italic: true, color: "#595959" }, wrapText: true };
coding.getRange("A3:S3").format = {
  fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  wrapText: true, horizontalAlignment: "center", verticalAlignment: "center",
  borders: { preset: "inside", style: "thin", color: "#FFFFFF" },
};
coding.getRange(`A4:S${body.length + 3}`).format = {
  font: { name: "Arial", size: 10, color: "#1F1F1F" }, wrapText: true, verticalAlignment: "top",
  borders: { insideHorizontal: { style: "thin", color: "#D9E2F3" } },
};
coding.getRange(`I4:N${body.length + 3}`).format.fill = "#FFF2CC";
coding.getRange(`P4:Q${body.length + 3}`).format.fill = "#FFF2CC";
coding.getRange(`S4:S${body.length + 3}`).format.fill = "#FFF2CC";
coding.getRange("A:B").format.columnWidth = 17;
coding.getRange("C:C").format.columnWidth = 10;
coding.getRange("D:F").format.columnWidth = 20;
coding.getRange("G:G").format.columnWidth = 17;
coding.getRange("H:H").format.columnWidth = 38;
coding.getRange("I:J").format.columnWidth = 30;
coding.getRange("K:N").format.columnWidth = 22;
coding.getRange("O:O").format.columnWidth = 70;
coding.getRange("P:P").format.columnWidth = 45;
coding.getRange("Q:S").format.columnWidth = 20;
coding.getRange("3:3").format.rowHeight = 38;
coding.freezePanes.freezeRows(3);
coding.freezePanes.freezeColumns(2);
coding.showGridLines = false;
coding.tables.add(`A3:S${body.length + 3}`, true, "ReductionTrainingRound2").style = "TableStyleMedium2";

const listData = {
  "Action family": ["Building energy efficiency", "Carbon capture", "Credits and neutralization", "Engagement and incentives", "Fuel and reductant substitution", "IT and digital infrastructure efficiency", "Industrial energy and process efficiency", "Measurement and monitoring", "Operational energy efficiency", "Outcome context", "Planning, governance and finance", "Policy and external conditions", "Process gases and refrigerants", "Products, materials and waste", "Renewable electricity", "Transport and mobility"],
  "Item role": ["Credits and neutralization", "Engagement and incentives", "External enabling condition", "Financing", "Measurement and monitoring", "Outcome context", "Physical intervention", "Planning and governance"],
  "Implementation stage": ["Completed", "Implementation commenced", "Implemented", "Investment made", "Not applicable", "Not stated", "Ongoing", "Pilot mentioned", "Planned", "Proposed", "Received", "Under construction", "Under investigation"],
  "Targeted emission scope": ["Downstream Scope 3", "Multiple scopes", "Not applicable", "Not stated", "Scope 1", "Scope 2", "Upstream Scope 3"],
  "Counterparty": ["Customer", "Employee", "Government or regulator", "Internal", "Landlord/building manager", "Lender", "Logistics provider", "Multiple", "Not stated", "Supplier", "Tenant", "Transport provider"],
  "Review status": ["Complete", "Needs discussion", "Exclude"],
  "Counts as action": ["No", "Yes"],
};
const listNames = Object.keys(listData);
listNames.forEach((name, col) => {
  lists.getCell(0, col).values = [[name]];
  lists.getRangeByIndexes(1, col, listData[name].length, 1).values = listData[name].map(value => [value]);
});
lists.getRange("A1:G1").format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" } };
lists.getRange("A:G").format.columnWidth = 34;
lists.showGridLines = false;

const end = body.length + 3;
const validationMap = [
  ["J4:J" + end, "A", listData["Action family"].length],
  ["K4:K" + end, "B", listData["Item role"].length],
  ["L4:L" + end, "C", listData["Implementation stage"].length],
  ["M4:M" + end, "D", listData["Targeted emission scope"].length],
  ["N4:N" + end, "E", listData["Counterparty"].length],
  ["Q4:Q" + end, "F", listData["Review status"].length],
  ["S4:S" + end, "G", listData["Counts as action"].length],
];
validationMap.forEach(([range, col, count]) => {
  coding.getRange(range).dataValidation = { rule: { type: "list", formula1: `'Coding lists'!$${col}$2:$${col}$${count + 1}` } };
});

const inspect = await workbook.inspect({ kind: "table", sheetId: "Reduction actions", range: "A1:S10", include: "values,formulas", tableMaxRows: 10, tableMaxCols: 19 });
console.log(inspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "Reduction actions", range: "A1:S12", scale: 1, format: "png" });
await fs.writeFile(`${root}/data/processed/cdp_section_datasets/cdp_reduction_training_round_2_preview.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, rows: body.length }));
