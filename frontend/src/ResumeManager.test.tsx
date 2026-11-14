import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import ResumeManager from './ResumeManager'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

describe('resume workspace', () => {
  it('offers login and registration and switches between them', () => {
    render(<ResumeManager />)
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(screen.getByRole('heading', { name: 'Create your account' })).toBeTruthy()
  })

  it('rejects unsupported file extensions before uploading', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'access', refresh_token: 'refresh' }), { status: 201 }))
      .mockResolvedValueOnce(new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ResumeManager />)
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a-long-enough-passphrase' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('button', { name: 'Sign out' })
    fireEvent.change(screen.getByLabelText('Upload a resume'), { target: { files: [new File(['x'], 'malware.exe')] } })
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PDF or DOCX file.')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('accepts a valid resume and reloads the library', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'access', refresh_token: 'refresh' }), { status: 201 }))
      .mockResolvedValueOnce(new Response('[]', { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: '1' }), { status: 201 }))
      .mockResolvedValueOnce(new Response('[]', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ResumeManager />)
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'person@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a-long-enough-passphrase' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('button', { name: 'Sign out' })
    fireEvent.change(screen.getByLabelText('Upload a resume'), { target: { files: [new File(['%PDF-x'], 'cv.pdf', { type: 'application/pdf' })] } })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
    expect(await screen.findByRole('status')).toHaveTextContent('Resume uploaded.')
  })
})
