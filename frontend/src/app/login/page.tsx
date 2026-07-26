'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import * as z from 'zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const formSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})

type FormData = z.infer<typeof formSchema>

export default function LoginPage() {
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(formSchema) })

  const onSubmit = async (data: FormData) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: data.email, password: data.password }),
        credentials: 'include',
      })
      if (!res.ok) {
        const body = await res.json()
        setError(body.detail || 'Login failed')
        return
      }
      const tokens = await res.json()
      if (typeof window !== 'undefined') {
        localStorage.setItem('access_token', tokens.access_token)
      }
      router.push('/dashboard')
    } catch {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-2 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Sign in to QuantX AI</h1>
          <p className="text-sm text-muted-foreground">Enter your credentials to access your trading account</p>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" {...register('email')} autoComplete="email" />
            {errors.email && <p className="text-sm text-red-400">{errors.email.message}</p>}
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" {...register('password')} autoComplete="current-password" />
            {errors.password && <p className="text-sm text-red-400">{errors.password.message}</p>}
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Signing in...' : 'Sign in'}
          </Button>
        </form>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-background px-2 text-muted-foreground">Or continue with</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <OAuthButton provider="google" label="Google" />
          <OAuthButton provider="github" label="GitHub" />
        </div>

        <p className="text-center text-sm text-muted-foreground">
          Don&apos;t have an account? <Link href="/register" className="underline">Create one</Link>
        </p>
      </div>
    </div>
  )
}

function OAuthButton({ provider, label }: { provider: string; label: string }) {
  const [loading, setLoading] = useState(false)

  const handleClick = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/v1/auth/oauth/${provider}`)
      if (!res.ok) {
        console.error('OAuth redirect failed')
        return
      }
      const data = await res.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch {
      console.error('OAuth redirect error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Button variant="outline" className="w-full" onClick={handleClick} disabled={loading}>
      {loading ? 'Connecting...' : label}
    </Button>
  )
}
