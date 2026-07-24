/* Bridge for the consistency test: reads a JSON array of point winners (1|2) from argv[2]
   and prints the client engine's storage-sets, so Python can compare client vs server. */
const E = require("./static/engine.js");
const points = JSON.parse(process.argv[2] || "[]");
process.stdout.write(JSON.stringify(E.allSetsForStorage(points)));
