/** RFC 4180 CSV parser (quoted fields, doubled quotes, CRLF/LF, embedded newlines). No dependencies. */
export function parseCsv(text: string): string[][] {
  const input = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  let index = 0;

  const endField = () => {
    row.push(field);
    field = "";
  };
  const endRow = () => {
    endField();
    rows.push(row);
    row = [];
  };

  while (index < input.length) {
    const char = input[index];
    if (quoted) {
      if (char === '"') {
        if (input[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"' && field === "") {
      quoted = true;
    } else if (char === ",") {
      endField();
    } else if (char === "\r") {
      if (input[index + 1] === "\n") index += 1;
      endRow();
    } else if (char === "\n") {
      endRow();
    } else {
      field += char;
    }
    index += 1;
  }
  if (field !== "" || row.length > 0) endRow();
  return rows;
}
