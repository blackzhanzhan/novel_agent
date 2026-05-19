import { FileType, HotFileItem } from '../types/store';

export type FileTreeNodeKind = 'root' | 'group' | 'folder' | 'file';

export interface FileTreeNode {
    id: string;
    parentId: string | null;
    kind: FileTreeNodeKind;
    label: string;
    sortKey: string;
    file?: HotFileItem;
    childrenIds: string[];
}

export interface FileTreeModel {
    rootId: string;
    nodes: Record<string, FileTreeNode>;
    defaultExpandedIds: string[];
}

type GroupDef = {
    key: string;
    title: string;
    fileType: FileType;
};

const GROUPS: GroupDef[] = [
    { key: 'world_core', title: '核心记忆', fileType: 'world_core' },
    { key: 'summary', title: '剧情总纲', fileType: 'summary' },
    { key: 'outline', title: '大纲文件', fileType: 'outline' },
    { key: 'style', title: '文风', fileType: 'style' },
    { key: 'error_archive', title: '错误档案', fileType: 'error_archive' },
    { key: 'chapter', title: '章节', fileType: 'chapter' },
];

function createNode(node: Omit<FileTreeNode, 'childrenIds'>): FileTreeNode {
    return {
        ...node,
        childrenIds: [],
    };
}

function sortChildren(nodes: Record<string, FileTreeNode>, parentId: string): void {
    const parent = nodes[parentId];
    if (!parent) return;
    parent.childrenIds.sort((a, b) => {
        const left = nodes[a];
        const right = nodes[b];
        if (!left || !right) return 0;
        return left.sortKey.localeCompare(right.sortKey, 'en');
    });
}

export function buildFileTreeModel(files: HotFileItem[]): FileTreeModel {
    const rootId = 'root';
    const nodes: Record<string, FileTreeNode> = {
        [rootId]: createNode({
            id: rootId,
            parentId: null,
            kind: 'root',
            label: '文件',
            sortKey: '000_root',
        }),
    };

    const defaultExpandedIds: string[] = [];

    for (const [index, group] of GROUPS.entries()) {
        const groupId = `group:${group.key}`;
        nodes[groupId] = createNode({
            id: groupId,
            parentId: rootId,
            kind: 'group',
            label: group.title,
            sortKey: `${String(index).padStart(2, '0')}_${group.title.toLowerCase()}`,
        });
        nodes[rootId].childrenIds.push(groupId);
        defaultExpandedIds.push(groupId);
    }
    sortChildren(nodes, rootId);

    const sortedFiles = [...files].sort((a, b) => a.fileName.localeCompare(b.fileName, 'en'));
    for (const file of sortedFiles) {
        const group = GROUPS.find((item) => item.fileType === file.fileType);
        if (!group) continue;

        const groupId = `group:${group.key}`;
        const normalizedPath = String(file.fileName || '').replace(/\\/g, '/').replace(/^\/+/, '');
        if (!normalizedPath) continue;

        const segments = normalizedPath.split('/').filter(Boolean);
        let parentId = groupId;
        let folderPath = '';
        for (const segment of segments.slice(0, -1)) {
            folderPath = folderPath ? `${folderPath}/${segment}` : segment;
            const folderId = `folder:${group.key}:${folderPath}`;
            if (!nodes[folderId]) {
                nodes[folderId] = createNode({
                    id: folderId,
                    parentId,
                    kind: 'folder',
                    label: segment,
                    sortKey: `folder_${segment.toLowerCase()}`,
                });
                nodes[parentId].childrenIds.push(folderId);
                defaultExpandedIds.push(folderId);
                sortChildren(nodes, parentId);
            }
            parentId = folderId;
        }

        const fileId = `file:${normalizedPath}`;
        if (!nodes[fileId]) {
            nodes[fileId] = createNode({
                id: fileId,
                parentId,
                kind: 'file',
                label: file.label || segments[segments.length - 1] || normalizedPath,
                sortKey: `file_${normalizedPath.toLowerCase()}`,
                file: {
                    ...file,
                    fileName: normalizedPath,
                },
            });
            nodes[parentId].childrenIds.push(fileId);
            sortChildren(nodes, parentId);
        }
    }

    return { rootId, nodes, defaultExpandedIds };
}

export function isFolderLikeNode(node: FileTreeNode): boolean {
    return node.kind === 'root' || node.kind === 'group' || node.kind === 'folder';
}

export function isFileNode(node: FileTreeNode): boolean {
    return node.kind === 'file';
}
