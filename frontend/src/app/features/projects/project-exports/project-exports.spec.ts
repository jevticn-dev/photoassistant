import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';

import { provideTranslations } from '../../../core/i18n/translation.config';
import {
  PhotoApi,
  type JobState,
  type Project,
  type VersionEntry,
} from '../../../shared/photos/photo-api';
import { ProjectExports } from './project-exports';

const PROJECT = '0199a1f0-0000-7000-8000-000000000001';

function recipe(contrast: number): unknown {
  return {
    schema: 1,
    white_balance: { temperature: 0, tint: 0 },
    tone: { exposure: 0, contrast, highlights: 0, shadows: 0, whites: 0, blacks: 0 },
    color: { saturation: 0, vibrance: 0 },
    tone_curve: {
      points: [
        [0, 0],
        [1, 1],
      ],
    },
  };
}

function version(label: string, contrast: number): VersionEntry {
  return {
    id: `version-${label}`,
    label,
    createdAt: '2026-09-21T10:00:00+00:00',
    edit: recipe(contrast),
  };
}

function job(status: JobState['status'], edit: unknown, error: string | null = null): JobState {
  return {
    id: `job-${status}-${String(error)}`,
    status,
    createdAt: '2026-09-21T11:00:00+00:00',
    updatedAt: '2026-09-21T11:00:00+00:00',
    error,
    edit,
    result:
      status === 'done'
        ? {
            key: 'k.png',
            contentType: 'image/png',
            width: 6000,
            height: 4000,
            bytes: 26_214_400,
          }
        : null,
  };
}

/**
 * The list of a project's exports.
 *
 * <p>The column worth testing is the one that is not stored: which version an
 * export was. An export carries the recipe that was on screen, not a version
 * (§B126), so the answer is a comparison — and the case where it matches
 * nothing is ordinary rather than a gap.</p>
 */
describe('ProjectExports', () => {
  let fixture: ComponentFixture<ProjectExports>;
  let downloaded: string | null;

  async function open(
    exports: readonly JobState[],
    versions: readonly VersionEntry[] = [version('V01', 10), version('V02', 20)],
    fails = false,
  ): Promise<void> {
    downloaded = null;

    await TestBed.configureTestingModule({
      imports: [ProjectExports],
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: (): string => PROJECT } } },
        },
        provideTranslations(),
        {
          provide: PhotoApi,
          useValue: {
            project: (): Observable<Project> =>
              of({
                id: PROJECT,
                name: 'Alpine Ridge',
                photoId: '0199a1f0-0000-7000-8000-000000000002',
                createdAt: '2026-09-21T10:00:00+00:00',
                versionCount: versions.length,
                hasChoice: true,
                startingEdit: null,
              }),
            versions: (): Observable<readonly VersionEntry[]> =>
              fails ? throwError(() => ({ summaryKey: 'errors.unreachable' })) : of(versions),
            exports: (): Observable<readonly JobState[]> => of(exports),
            download: (id: string): Observable<Blob> => {
              downloaded = id;

              return of(new Blob([new Uint8Array([137])], { type: 'image/png' }));
            },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectExports);
    fixture.detectChanges();
  }

  afterEach(() => TestBed.resetTestingModule());

  function text(): string {
    return (fixture.nativeElement as HTMLElement).textContent ?? '';
  }

  function rows(): HTMLElement[] {
    return [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.export')];
  }

  it('names the version an export was, when its recipe is one that was saved', async () => {
    await open([job('done', recipe(20))]);

    expect(rows()).toHaveLength(1);
    expect(text()).toContain('exports.version');
    expect(text()).not.toContain('exports.unsavedEdit');
  });

  it('says so plainly when the export was of an edit that was never saved', async () => {
    // Ordinary rather than exceptional: exporting does not save a version, and
    // the two are deliberately unlinked.
    await open([job('done', recipe(77))]);

    expect(text()).toContain('exports.unsavedEdit');
  });

  it('a document that is not a recipe matches nothing rather than matching anything', async () => {
    await open([job('done', { nonsense: true })]);

    expect(text()).toContain('exports.unsavedEdit');
  });

  it('a finished export offers its file and says how big it is', async () => {
    await open([job('done', recipe(10))]);

    expect(text()).toContain('exports.size');
    expect(text()).toContain('exports.download');
  });

  it('one still rendering offers nothing to download', async () => {
    await open([job('running', recipe(10))]);

    expect(text()).toContain('exports.working');
    expect(text()).not.toContain('exports.download');
  });

  it('a failed export shows the reason the worker gave', async () => {
    await open([job('failed', recipe(10), 'the original is no longer stored')]);

    expect(text()).toContain('exports.failed');
    expect(text()).toContain('no longer stored');
  });

  it('a project with no exports says so instead of showing an empty list', async () => {
    await open([]);

    expect(rows()).toHaveLength(0);
    expect(text()).toContain('exports.empty.title');
  });

  it('downloading asks for that job, not the newest', async () => {
    const older = job('done', recipe(10));
    const newer = job('done', recipe(20));

    await open([newer, older]);

    const buttons = [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')].filter(
      (button) => button.textContent?.trim() === 'exports.download',
    );

    buttons[1].click();
    fixture.detectChanges();

    expect(downloaded).toBe(older.id);
  });

  it('a failure is said, with a way to try again', async () => {
    await open([], [], true);

    expect(text()).toContain('errors.unreachable');
    expect(text()).toContain('common.retry');
  });
});
