import type { ReactNode } from "react";

export function renderInline(text: string): ReactNode {
  const segs: ReactNode[] = [];
  let i = 0; let buf = ""; let key = 0;
  while (i < text.length) {
    if (text.startsWith("**", i)) {
      if (buf) { segs.push(buf); buf = ""; }
      const end = text.indexOf("**", i + 2);
      if (end !== -1) { segs.push(<strong key={key++}>{text.slice(i + 2, end)}</strong>); i = end + 2; continue; }
    }
    if (text[i] === "`") {
      if (buf) { segs.push(buf); buf = ""; }
      const end = text.indexOf("`", i + 1);
      if (end !== -1) {
        segs.push(<code key={key++} style={{ fontFamily: "var(--font-mono)", background: "rgba(255,255,255,0.09)", padding: "1px 4px", borderRadius: 3, fontSize: "0.88em" }}>{text.slice(i + 1, end)}</code>);
        i = end + 1; continue;
      }
    }
    if (text[i] === "*" && !text.startsWith("**", i)) {
      if (buf) { segs.push(buf); buf = ""; }
      const end = text.indexOf("*", i + 1);
      if (end !== -1 && !text.startsWith("**", end)) { segs.push(<em key={key++}>{text.slice(i + 1, end)}</em>); i = end + 1; continue; }
    }
    buf += text[i]; i++;
  }
  if (buf) segs.push(buf);
  return <>{segs}</>;
}

export function MdView({ content }: { content: string }) {
  const nodes: ReactNode[] = [];
  const lines = content.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) { codeLines.push(lines[i]); i++; }
      i++;
      nodes.push(
        <pre key={nodes.length} style={{ background: "rgba(0,0,0,0.35)", padding: "8px 10px", borderRadius: 5, overflowX: "auto", fontSize: 10, fontFamily: "var(--font-mono)", margin: "5px 0", border: "1px solid var(--border)", lineHeight: 1.5 }}>
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    const hm = line.match(/^(#{1,4}) (.*)/);
    if (hm) {
      const sizes = [null, 14, 13, 12, 11];
      nodes.push(
        <div key={nodes.length} style={{ fontWeight: 700, fontSize: sizes[hm[1].length] ?? 12, color: "var(--text)", margin: "10px 0 3px", lineHeight: 1.3 }}>
          {renderInline(hm[2])}
        </div>
      );
      i++; continue;
    }

    if (line.match(/^[-_*]{3,}$/)) {
      nodes.push(<div key={nodes.length} style={{ borderTop: "1px solid var(--border)", margin: "6px 0" }} />);
      i++; continue;
    }

    if (line.match(/^[-*] /)) {
      const items: ReactNode[] = [];
      while (i < lines.length && lines[i].match(/^[-*] /)) {
        const txt = lines[i].replace(/^[-*] /, "");
        items.push(<div key={i} style={{ paddingLeft: 10, fontSize: 11, color: "var(--text)", marginBottom: 1, lineHeight: 1.5 }}>• {renderInline(txt)}</div>);
        i++;
      }
      nodes.push(<div key={nodes.length} style={{ margin: "3px 0" }}>{items}</div>);
      continue;
    }

    if (line.match(/^\d+\. /)) {
      const items: ReactNode[] = [];
      while (i < lines.length && lines[i].match(/^\d+\. /)) {
        const txt = lines[i].replace(/^\d+\. /, "");
        items.push(<div key={i} style={{ paddingLeft: 10, fontSize: 11, color: "var(--text)", marginBottom: 1, lineHeight: 1.5 }}>{lines[i].match(/^\d+/)![0]}. {renderInline(txt)}</div>);
        i++;
      }
      nodes.push(<div key={nodes.length} style={{ margin: "3px 0" }}>{items}</div>);
      continue;
    }

    if (!line.trim()) { nodes.push(<div key={nodes.length} style={{ height: 5 }} />); i++; continue; }

    nodes.push(
      <div key={nodes.length} style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.5, marginBottom: 2 }}>
        {renderInline(line)}
      </div>
    );
    i++;
  }
  return <div style={{ wordBreak: "break-word" }}>{nodes}</div>;
}
