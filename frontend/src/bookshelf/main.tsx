import React from 'react'
import ReactDOM from 'react-dom/client'
import { BookshelfApp } from './BookshelfApp'
import '../index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <BookshelfApp />
    </React.StrictMode>,
)
