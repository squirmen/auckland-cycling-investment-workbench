// Small DOM helpers. Source strings are always set as text, never as markup.

export function requiredElement<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Required interface element is missing: ${id}`);
  return element as T;
}

export function create<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Record<string, string> & { text?: string; className?: string } = {},
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "text") element.textContent = value;
    else if (key === "className") element.className = value;
    else if (key === "htmlFor" && element instanceof HTMLLabelElement) element.htmlFor = value;
    else element.setAttribute(key, value);
  }
  return element;
}

export function svgElement(tag: string, attributes: Record<string, string | number>): SVGElement {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "textContent") element.textContent = String(value);
    else element.setAttribute(key, String(value));
  }
  return element;
}

export function svgText(
  x: number,
  y: number,
  text: string,
  className: string,
  anchor: "start" | "middle" | "end" = "middle",
): SVGElement {
  return svgElement("text", { x, y, class: className, "text-anchor": anchor, textContent: text });
}
