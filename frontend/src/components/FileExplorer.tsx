import React, { useMemo } from 'react';
import { hotkeysCoreFeature, syncDataLoaderFeature } from '@headless-tree/core';
import { useTree } from '@headless-tree/react';
import { useUiCopy } from '../i18n/ui';
import { HotFileItem } from '../types/store';
import { buildFileTreeModel, FileTreeNode, isFileNode, isFolderLikeNode } from '../lib/fileTree';

interface FileExplorerProps {
    files: HotFileItem[];
    activeFile: string;
    disabled?: boolean;
    hotkeysEnabled?: boolean;
    onSelectFile: (file: HotFileItem) => void;
}

export const FileExplorer: React.FC<FileExplorerProps> = ({
    files,
    activeFile,
    disabled = false,
    hotkeysEnabled = true,
    onSelectFile,
}) => {
    const copy = useUiCopy();
    const model = useMemo(() => buildFileTreeModel(files), [files]);
    const missingNode = useMemo<FileTreeNode>(() => ({
        id: '__missing__',
        parentId: null,
        kind: 'folder',
        label: '',
        sortKey: 'zzz_missing',
        childrenIds: [],
    }), []);
    const features = useMemo(
        () => (hotkeysEnabled ? [syncDataLoaderFeature, hotkeysCoreFeature] : [syncDataLoaderFeature]),
        [hotkeysEnabled]
    );

    const tree = useTree<FileTreeNode>({
        rootItemId: model.rootId,
        getItemName: (item) => item.getItemData().label,
        isItemFolder: (item) => isFolderLikeNode(item.getItemData()),
        dataLoader: {
            getItem: (itemId) => model.nodes[itemId] || { ...missingNode, id: String(itemId) },
            getChildren: (itemId) => model.nodes[itemId]?.childrenIds || [],
        },
        indent: 14,
        initialState: {
            expandedItems: model.defaultExpandedIds,
        },
        features,
    });

    const visibleItems = tree.getItems().filter((item) => item.getId() !== model.rootId);

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
            <div className="app-scrollbar min-h-0 flex-1 overflow-y-auto px-1.5 py-2">
                <div {...tree.getContainerProps(copy.explorer.treeAriaLabel)} className="space-y-0.5">
                    {visibleItems.map((item) => {
                        const node = item.getItemData();
                        const isFile = isFileNode(node);
                        const isActive = Boolean(isFile && node.file?.fileName === activeFile);
                        const depth = Math.max(item.getItemMeta().level - 1, 0);
                        const leftPadding = 8 + depth * 14;
                        const rawProps = item.getProps() as React.ButtonHTMLAttributes<HTMLButtonElement>;
                        const isExpanded = item.isFolder() ? item.isExpanded() : false;
                        return (
                            <button
                                key={item.getId()}
                                type="button"
                                {...rawProps}
                                disabled={disabled}
                                onClick={(event) => {
                                    rawProps.onClick?.(event);
                                    if (!disabled && isFile && node.file) {
                                        onSelectFile(node.file);
                                    }
                                }}
                                style={{ paddingLeft: `${leftPadding}px` }}
                                className={`group w-full rounded-[8px] border-l border-transparent py-1.5 pr-2 text-left text-xs transition-all ${
                                    isActive
                                        ? 'border-[rgba(255,255,255,0.14)] bg-[rgba(255,255,255,0.018)] text-[var(--color-dark-text-main)]'
                                        : 'text-[var(--color-dark-text-main)] hover:border-[rgba(255,255,255,0.08)] hover:bg-[rgba(255,255,255,0.012)]'
                                } disabled:cursor-not-allowed disabled:opacity-60`}
                            >
                                <div className="flex items-start gap-2">
                                    <span className={`mt-0.5 w-3 text-[10px] ${isFile ? 'opacity-0' : 'opacity-70'}`}>
                                        {isExpanded ? '▾' : '▸'}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <div className={`flex items-center gap-2 truncate ${node.kind === 'group' ? 'text-[9px] tracking-[0.12em] text-[var(--color-dark-text-faint)]' : ''}`}>
                                            <span className="truncate">{node.label}</span>
                                            {isFile && node.file?.virtual && (
                                                <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-mono ${
                                                        isActive
                                                            ? 'border-[#d9ecff66] text-[#eef7ff]'
                                                            : 'border-[var(--color-dark-border)] text-[var(--color-dark-text-faint)]'
                                                }`}>
                                                    {copy.explorer.virtualBadge}
                                                </span>
                                            )}
                                        </div>
                                        {isFile && node.file && (
                                            <div className={`truncate text-[10px] ${isActive ? 'text-[var(--color-dark-text-faint)]' : 'text-[var(--color-dark-text-faint)]'}`}>
                                                {node.file.fileName}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </button>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};
