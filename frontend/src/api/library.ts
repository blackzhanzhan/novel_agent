import { fetchApi } from './client';

export interface BookListItem {
    book_id: string;
    book_name: string;
}

export interface DeleteBookResult {
    status: 'success';
    book_id: string;
    book_name?: string;
    cleanup_pending?: boolean;
    note?: string;
}

export async function fetchBooksList(): Promise<BookListItem[]> {
    const response = await fetchApi<{ status: 'success'; total: number; books: BookListItem[] }>('/books/list');
    return response.books;
}

export async function deleteBook(bookId: string): Promise<DeleteBookResult> {
    return await fetchApi<DeleteBookResult>(`/books/${encodeURIComponent(bookId)}`, { method: 'DELETE' });
}
