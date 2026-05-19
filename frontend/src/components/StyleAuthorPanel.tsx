import React, { useMemo } from 'react';
import { buildStyleAuthorLens, type StyleSectionTone } from '../lib/styleAuthorLens';

interface StyleAuthorPanelProps {
    fileName: string;
    content: string;
    rawReport: React.ReactNode;
}

function bulletClass(tone: StyleSectionTone): string {
    if (tone === 'warning') return 'bg-[var(--color-accent-amber)]';
    if (tone === 'accent') return 'bg-[var(--color-accent-blue)]';
    return 'bg-[var(--color-dark-text-faint)]';
}

export const StyleAuthorPanel: React.FC<StyleAuthorPanelProps> = ({ fileName, content, rawReport }) => {
    const lens = useMemo(() => buildStyleAuthorLens(fileName, content), [fileName, content]);

    return (
        <div className="space-y-5 pb-8 text-[var(--color-dark-text-main)]">
            <section className="border-b border-[rgba(255,255,255,0.06)] pb-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                        <div className="cursor-section-label">{lens.eyebrow}</div>
                        <h1 className="mt-2 text-[2rem] font-semibold leading-tight tracking-normal text-[var(--color-dark-text-main)]">
                            {lens.title}
                        </h1>
                    </div>
                    <div className="rounded-full border border-[rgba(255,255,255,0.08)] px-3 py-1 text-[10px] font-mono text-[var(--color-dark-text-faint)]">
                        {lens.sourceLabel}
                    </div>
                </div>
                <p className="mt-4 max-w-4xl text-[15px] leading-7 text-[var(--color-dark-text-muted)]">
                    {lens.voiceSummary}
                </p>
                <div className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(128px,1fr))] gap-2">
                    {lens.metricBadges.map((item) => (
                        <div
                            key={item.label}
                            className="rounded-[8px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.025)] px-3 py-2"
                        >
                            <div className="text-[10px] text-[var(--color-dark-text-faint)]">{item.label}</div>
                            <div className="mt-1 font-mono text-[13px] text-[var(--color-dark-text-main)]">{item.value}</div>
                            <div className="mt-0.5 text-[10px] text-[var(--color-dark-text-muted)]">{item.note}</div>
                        </div>
                    ))}
                </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-2">
                {lens.sections.map((section) => (
                    <section
                        key={section.title}
                        className="rounded-[8px] border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.018)] p-4"
                    >
                        <h2 className="text-[15px] font-semibold text-[var(--color-dark-text-main)]">{section.title}</h2>
                        <ul className="mt-3 space-y-2 text-[13px] leading-6 text-[var(--color-dark-text-muted)]">
                            {section.items.map((item, index) => (
                                <li key={`${section.title}-${index}`} className="flex gap-2">
                                    <span className={`mt-[0.62rem] h-1.5 w-1.5 shrink-0 rounded-full ${bulletClass(section.tone)}`} />
                                    <span>{item}</span>
                                </li>
                            ))}
                        </ul>
                    </section>
                ))}
            </div>

            <section className="border-t border-[rgba(255,255,255,0.06)] pt-4">
                <h2 className="text-[13px] font-semibold text-[var(--color-dark-text-main)]">{lens.evidenceTitle}</h2>
                <div className="mt-2 space-y-1.5 text-[11px] leading-5 text-[var(--color-dark-text-faint)]">
                    {lens.evidenceItems.map((item, index) => (
                        <div key={`evidence-${index}`} className="break-words">{item}</div>
                    ))}
                </div>
            </section>

            <details className="group rounded-[8px] border border-[rgba(255,255,255,0.06)] bg-[rgba(0,0,0,0.12)]">
                <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[12px] font-semibold text-[var(--color-dark-text-muted)]">
                    <span>{lens.rawReportLabel}</span>
                    <span className="text-[10px] text-[var(--color-dark-text-faint)] transition-transform group-open:rotate-90">›</span>
                </summary>
                <div className="border-t border-[rgba(255,255,255,0.05)] px-4 py-4">
                    {rawReport}
                </div>
            </details>
        </div>
    );
};
