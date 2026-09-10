"use client";

import Editor, { type OnMount } from "@monaco-editor/react";

import type { Language } from "@/types";

interface CodeEditorProps {
  value: string;
  language: Language;
  onChange: (value: string) => void;
}

export function CodeEditor({ value, language, onChange }: CodeEditorProps) {
  const handleMount: OnMount = (editor) => {
    const layoutEditor = () => {
      const container = editor.getContainerDomNode().parentElement;
      if (container) {
        editor.layout({
          width: container.clientWidth,
          height: container.clientHeight,
        });
      }
    };
    requestAnimationFrame(layoutEditor);
    setTimeout(layoutEditor, 100);
  };

  return (
    <Editor
      height="100%"
      width="100%"
      language={language}
      theme="vs-dark"
      value={value}
      onChange={(nextValue) => onChange(nextValue ?? "")}
      onMount={handleMount}
      options={{
        automaticLayout: true,
        fontSize: 14,
        fontFamily: "var(--font-mono), Consolas, monospace",
        minimap: { enabled: false },
        padding: { top: 16, bottom: 16 },
        scrollBeyondLastLine: false,
        smoothScrolling: true,
        tabSize: 4,
      }}
      loading={<div className="output-empty">Loading editor…</div>}
    />
  );
}
