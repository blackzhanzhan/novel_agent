import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MarkdownRenderProps {
    content: string;
    className?: string;
}

const BASE_MARKDOWN_CLASS =
    'prose prose-invert max-w-none text-[var(--color-dark-text-main)] ' +
    'prose-headings:font-semibold prose-headings:tracking-[-0.01em] prose-h1:mt-0 prose-h1:mb-5 prose-h1:text-[2.1rem] prose-h1:leading-[1.08] prose-h2:mt-7 prose-h2:mb-3 prose-h2:text-[1.58rem] prose-h2:leading-[1.12] prose-h3:mt-5 prose-h3:mb-2 prose-h3:text-[1.28rem] prose-h3:leading-[1.2] prose-h4:mt-4 prose-h4:mb-2 prose-h4:text-[1.08rem] prose-h4:leading-[1.28] prose-p:my-1.5 prose-ul:my-1.5 prose-ol:my-1.5 prose-li:my-0.5 prose-ul:pl-[1.15em] prose-ol:pl-[1.3em] ' +
    'prose-strong:text-[var(--color-dark-text-main)] prose-a:text-[var(--color-accent-blue)] ' +
    'prose-code:text-[var(--color-accent-blue)] prose-pre:my-2 prose-pre:border ' +
    'prose-pre:border-[var(--color-dark-border)] prose-pre:bg-[#0b1119] [&_p]:leading-[1.72] [&_li]:leading-[1.68] [&_li>p]:my-0 [&_ul]:leading-[1.68] [&_ol]:leading-[1.68]';

const MARKDOWN_PLUGINS = [remarkGfm];

const MarkdownRenderImpl: React.FC<MarkdownRenderProps> = ({ content, className }) => {
    if (!content) return null;

    return (
        <div className={`${BASE_MARKDOWN_CLASS} ${className || ''}`.trim()}>
            <ReactMarkdown remarkPlugins={MARKDOWN_PLUGINS}>
                {content}
            </ReactMarkdown>
        </div>
    );
};

export const MarkdownRender = React.memo(MarkdownRenderImpl);
