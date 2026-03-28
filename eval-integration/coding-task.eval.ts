/**
 * @license
 * Copyright 2026 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

// NOTE: This is a conceptual demonstration of how CodingTaskManifest-based
// evaluations integrate with Gemini CLI's existing eval infrastructure.
// In the full implementation, CodingTaskRunner would handle repo cloning
// and task setup automatically from manifest files.
//
// This demo uses the existing evalTest() + TestRig pattern with inline
// files to show a Level 2 (cross-file) coding task.

import {describe} from 'vitest';
import {evalTest} from '../evals/test-helper.js';
import type {TestRig} from '../evals/test-helper.js';

describe('coding_tasks', () => {
  evalTest('USUALLY_PASSES', {
    name: 'L2: auth middleware context propagation bug',
    prompt: `The auth middleware is not properly propagating the user context to downstream route handlers. When a user is authenticated, the req.user object is set in the middleware but it's undefined by the time it reaches the route handler. Investigate and fix the issue.`,
    files: {
      'package.json': JSON.stringify(
        {
          name: 'task-demo-auth-context',
          version: '1.0.0',
          private: true,
          scripts: {
            start: 'ts-node src/server.ts',
            test: 'jest --config jest.config.js',
          },
          dependencies: {
            express: '^4.18.2',
            jsonwebtoken: '^9.0.2',
          },
          devDependencies: {
            '@types/express': '^4.17.21',
            '@types/jsonwebtoken': '^9.0.5',
            '@types/jest': '^29.5.12',
            '@types/supertest': '^6.0.2',
            jest: '^29.7.0',
            supertest: '^6.3.4',
            'ts-jest': '^29.1.2',
            'ts-node': '^10.9.2',
            typescript: '^5.3.3',
          },
        },
        null,
        2,
      ),

      'src/types.ts': `import type {Request} from 'express';

export interface UserPayload {
  id: string;
  email: string;
  role: 'admin' | 'user' | 'viewer';
  organizationId: string;
}

export interface AuthenticatedRequest extends Request {
  user?: UserPayload;
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface PaginationParams {
  page: number;
  limit: number;
  sortBy?: string;
  order?: 'asc' | 'desc';
}

export interface ProjectRecord {
  id: string;
  name: string;
  ownerId: string;
  organizationId: string;
  createdAt: string;
  updatedAt: string;
}
`,

      'src/config.ts': `export const config = {
  port: parseInt(process.env.PORT || '3000', 10),
  jwtSecret: process.env.JWT_SECRET || 'dev-secret-do-not-use-in-production',
  jwtExpiresIn: '24h',
  corsOrigins: (process.env.CORS_ORIGINS || 'http://localhost:3000').split(','),
  rateLimit: {
    windowMs: 15 * 60 * 1000,
    maxRequests: 100,
  },
  pagination: {
    defaultLimit: 20,
    maxLimit: 100,
  },
};
`,

      // The bug is here: authMiddleware creates a NEW request object via
      // Object.assign instead of mutating req in place. The spread creates
      // a shallow copy, so the original req passed down the middleware chain
      // never gets the .user property.
      'src/middleware/auth.ts': `import {Response, NextFunction} from 'express';
import jwt from 'jsonwebtoken';
import {config} from '../config.js';
import type {AuthenticatedRequest, UserPayload} from '../types.js';

/**
 * Verify the JWT from the Authorization header and attach the decoded
 * user payload to the request object for downstream handlers.
 */
export function authMiddleware(
  req: AuthenticatedRequest,
  res: Response,
  next: NextFunction,
): void {
  const header = req.headers.authorization;

  if (!header || !header.startsWith('Bearer ')) {
    res.status(401).json({success: false, error: 'Missing or malformed token'});
    return;
  }

  const token = header.slice(7);

  try {
    const decoded = jwt.verify(token, config.jwtSecret) as UserPayload;

    // Attach user context for downstream handlers
    const authenticatedReq = Object.assign({}, req, {user: decoded});
    req = authenticatedReq as AuthenticatedRequest;

    next();
  } catch (err) {
    if (err instanceof jwt.TokenExpiredError) {
      res.status(401).json({success: false, error: 'Token expired'});
      return;
    }
    res.status(401).json({success: false, error: 'Invalid token'});
  }
}

/**
 * Require a specific role. Must be used after authMiddleware.
 */
export function requireRole(...roles: UserPayload['role'][]) {
  return (req: AuthenticatedRequest, res: Response, next: NextFunction): void => {
    if (!req.user) {
      res.status(401).json({success: false, error: 'Not authenticated'});
      return;
    }
    if (!roles.includes(req.user.role)) {
      res.status(403).json({success: false, error: 'Insufficient permissions'});
      return;
    }
    next();
  };
}
`,

      'src/utils/pagination.ts': `import type {Request} from 'express';
import {config} from '../config.js';
import type {PaginationParams} from '../types.js';

export function parsePagination(req: Request): PaginationParams {
  const page = Math.max(1, parseInt(req.query.page as string, 10) || 1);
  const rawLimit = parseInt(req.query.limit as string, 10) || config.pagination.defaultLimit;
  const limit = Math.min(rawLimit, config.pagination.maxLimit);
  const sortBy = (req.query.sortBy as string) || undefined;
  const order = req.query.order === 'desc' ? 'desc' : 'asc';

  return {page, limit, sortBy, order};
}

export function paginateArray<T>(items: T[], params: PaginationParams): T[] {
  const start = (params.page - 1) * params.limit;
  return items.slice(start, start + params.limit);
}
`,

      'src/routes/projects.ts': `import {Router, Response} from 'express';
import {authMiddleware, requireRole} from '../middleware/auth.js';
import {parsePagination, paginateArray} from '../utils/pagination.js';
import type {AuthenticatedRequest, ApiResponse, ProjectRecord} from '../types.js';

const router = Router();

// In-memory store for demo purposes
const projects: ProjectRecord[] = [
  {
    id: 'proj-001',
    name: 'Frontend Redesign',
    ownerId: 'user-1',
    organizationId: 'org-acme',
    createdAt: '2026-01-15T10:00:00Z',
    updatedAt: '2026-03-20T14:30:00Z',
  },
  {
    id: 'proj-002',
    name: 'API Migration',
    ownerId: 'user-2',
    organizationId: 'org-acme',
    createdAt: '2026-02-01T09:00:00Z',
    updatedAt: '2026-03-25T16:45:00Z',
  },
  {
    id: 'proj-003',
    name: 'Mobile App v2',
    ownerId: 'user-1',
    organizationId: 'org-globex',
    createdAt: '2026-03-01T11:00:00Z',
    updatedAt: '2026-03-28T08:15:00Z',
  },
];

/**
 * GET /projects
 * List projects visible to the authenticated user, scoped by their organization.
 */
router.get('/', authMiddleware, (req: AuthenticatedRequest, res: Response) => {
  const user = req.user;
  if (!user) {
    res.status(401).json({success: false, error: 'Not authenticated'} as ApiResponse);
    return;
  }

  const orgProjects = projects.filter((p) => p.organizationId === user.organizationId);
  const pagination = parsePagination(req);
  const page = paginateArray(orgProjects, pagination);

  res.json({
    success: true,
    data: page,
  } as ApiResponse<ProjectRecord[]>);
});

/**
 * GET /projects/:id
 * Get a single project by ID, with organization-level access control.
 */
router.get('/:id', authMiddleware, (req: AuthenticatedRequest, res: Response) => {
  const user = req.user;
  if (!user) {
    res.status(401).json({success: false, error: 'Not authenticated'} as ApiResponse);
    return;
  }

  const project = projects.find(
    (p) => p.id === req.params.id && p.organizationId === user.organizationId,
  );

  if (!project) {
    res.status(404).json({success: false, error: 'Project not found'} as ApiResponse);
    return;
  }

  res.json({success: true, data: project} as ApiResponse<ProjectRecord>);
});

/**
 * DELETE /projects/:id
 * Delete a project. Requires admin role.
 */
router.delete(
  '/:id',
  authMiddleware,
  requireRole('admin'),
  (req: AuthenticatedRequest, res: Response) => {
    const user = req.user!;
    const idx = projects.findIndex(
      (p) => p.id === req.params.id && p.organizationId === user.organizationId,
    );

    if (idx === -1) {
      res.status(404).json({success: false, error: 'Project not found'} as ApiResponse);
      return;
    }

    projects.splice(idx, 1);
    res.json({success: true} as ApiResponse);
  },
);

export {router as projectsRouter};
`,

      'src/server.ts': `import express from 'express';
import {config} from './config.js';
import {projectsRouter} from './routes/projects.js';

const app = express();

app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({status: 'ok', timestamp: new Date().toISOString()});
});

app.use('/projects', projectsRouter);

app.use((_req, res) => {
  res.status(404).json({success: false, error: 'Not found'});
});

if (require.main === module) {
  app.listen(config.port, () => {
    console.log(\`Server running on port \${config.port}\`);
  });
}

export {app};
`,

      'tests/helpers.ts': `import jwt from 'jsonwebtoken';
import {config} from '../src/config.js';
import type {UserPayload} from '../src/types.js';

export function createTestToken(overrides: Partial<UserPayload> = {}): string {
  const payload: UserPayload = {
    id: 'user-1',
    email: 'alice@acme.com',
    role: 'admin',
    organizationId: 'org-acme',
    ...overrides,
  };
  return jwt.sign(payload, config.jwtSecret, {expiresIn: '1h'});
}

export function authHeader(token: string): Record<string, string> {
  return {Authorization: \`Bearer \${token}\`};
}
`,

      'tests/projects.test.ts': `import request from 'supertest';
import {app} from '../src/server.js';
import {createTestToken, authHeader} from './helpers.js';

describe('GET /projects', () => {
  it('returns 401 without a token', async () => {
    const res = await request(app).get('/projects');
    expect(res.status).toBe(401);
    expect(res.body.success).toBe(false);
  });

  it('returns projects for the authenticated user organization', async () => {
    const token = createTestToken({organizationId: 'org-acme'});
    const res = await request(app)
      .get('/projects')
      .set(authHeader(token));

    // BUG: This test should pass but currently fails because req.user
    // is undefined in the route handler due to the middleware bug.
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(res.body.data).toHaveLength(2); // org-acme has 2 projects
  });

  it('scopes projects by organization', async () => {
    const token = createTestToken({organizationId: 'org-globex'});
    const res = await request(app)
      .get('/projects')
      .set(authHeader(token));

    expect(res.status).toBe(200);
    expect(res.body.data).toHaveLength(1);
    expect(res.body.data[0].name).toBe('Mobile App v2');
  });
});

describe('GET /projects/:id', () => {
  it('returns a project by ID', async () => {
    const token = createTestToken({organizationId: 'org-acme'});
    const res = await request(app)
      .get('/projects/proj-001')
      .set(authHeader(token));

    expect(res.status).toBe(200);
    expect(res.body.data.name).toBe('Frontend Redesign');
  });

  it('returns 404 for a project in a different organization', async () => {
    const token = createTestToken({organizationId: 'org-globex'});
    const res = await request(app)
      .get('/projects/proj-001')
      .set(authHeader(token));

    expect(res.status).toBe(404);
  });
});

describe('DELETE /projects/:id', () => {
  it('requires admin role', async () => {
    const token = createTestToken({role: 'viewer'});
    const res = await request(app)
      .delete('/projects/proj-001')
      .set(authHeader(token));

    // This will also fail due to the auth middleware bug -- req.user
    // is undefined so requireRole always returns 401.
    expect(res.status).toBe(403);
  });
});
`,

      'jest.config.js': `/** @type {import('jest').Config} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  moduleFileExtensions: ['ts', 'js', 'json'],
};
`,
    },
    assert: async (rig: TestRig) => {
      // Verify the agent investigated the right files
      const readFiles = rig.getReadFiles();
      const authMiddlewareRead = readFiles.some(
        (f) =>
          f.includes('middleware/auth') ||
          f.includes('auth.ts'),
      );
      const routerRead = readFiles.some(
        (f) =>
          f.includes('routes/projects') ||
          f.includes('projects.ts'),
      );

      if (!authMiddlewareRead) {
        return {
          pass: false,
          message: 'Agent did not read the auth middleware file',
        };
      }
      if (!routerRead) {
        return {
          pass: false,
          message: 'Agent did not read the projects router file',
        };
      }

      // Verify the agent made edits
      const editedFiles = rig.getEditedFiles();
      const authEdited = editedFiles.some(
        (f) =>
          f.includes('middleware/auth') ||
          f.includes('auth.ts'),
      );

      if (!authEdited) {
        return {
          pass: false,
          message: 'Agent did not edit the auth middleware file',
        };
      }

      // Check the fix is correct: the auth middleware should mutate req.user
      // directly instead of creating a copy with Object.assign
      const authContent = rig.readFile('src/middleware/auth.ts');

      // The broken pattern: Object.assign({}, req, {user: decoded})
      // This creates a new object that doesn't affect the original req
      const stillBroken =
        authContent.includes('Object.assign({}, req') ||
        authContent.includes('Object.assign({},req');

      if (stillBroken) {
        return {
          pass: false,
          message:
            'Auth middleware still uses Object.assign to create a copy ' +
            'instead of mutating req directly',
        };
      }

      // The fix should directly assign to req.user
      const hasDirectAssignment =
        authContent.includes('req.user = decoded') ||
        authContent.includes('req.user=decoded') ||
        authContent.includes('(req as AuthenticatedRequest).user = decoded') ||
        authContent.includes('req.user = jwt.verify');

      if (!hasDirectAssignment) {
        return {
          pass: false,
          message:
            'Fix does not directly assign decoded user to req.user',
        };
      }

      return {pass: true};
    },
  });
});
