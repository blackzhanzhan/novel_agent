import { HotFileItem } from '../types/store';

export const DEFAULT_HOT_FILES: HotFileItem[] = [
    { fileName: 'world_model.md', fileType: 'world_core', label: '世界观底座' },
    { fileName: 'status_card.md', fileType: 'world_core', label: '状态卡' },
    { fileName: 'summary.md', fileType: 'summary', label: '剧情总纲' },
    { fileName: 'brainstorm.md', fileType: 'outline', label: '头脑风暴' },
    { fileName: 'master_outline.md', fileType: 'outline', label: '总纲' },
    { fileName: 'arc_outline.md', fileType: 'outline', label: '篇章大纲' },
    { fileName: 'chapter_outline.md', fileType: 'outline', label: '逐章大纲' },
    { fileName: 'chapter_draft.md', fileType: 'chapter', label: '续写草稿' },
    { fileName: 'style_guide.md', fileType: 'style', label: '文风指南' },
    { fileName: 'error_archive.md', fileType: 'error_archive', label: '错误档案' },
];
