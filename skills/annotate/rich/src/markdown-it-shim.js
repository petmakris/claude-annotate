// The page already loads markdown-it (static/markdown-it.min.js); the
// bundle uses that one instead of carrying a second copy.
export default function MarkdownIt(...args) { return window.markdownit(...args); }
