import ReactMarkdown from "react-markdown";

/**
 * Renders untrusted Markdown. react-markdown never emits raw HTML and its default URL transform
 * drops javascript: and similar schemes; links open in a new tab without referrer.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown" data-testid="markdown">
      <ReactMarkdown
        components={{
          a: ({ children: linkChildren, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {linkChildren}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
