import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { Observable, of } from 'rxjs';
import { vi } from 'vitest';

import { environment } from '../../../environments/environment';
import { provideTranslations } from '../../core/i18n/translation.config';
import {
  PhotoApi,
  type JobState,
  type Project,
  type SavedVersion,
  type VersionEntry,
} from '../../shared/photos/photo-api';
import { Editor } from './editor';
import { EditorService } from './editor-service';

/**
 * The export, through the real service and the real HTTP layer.
 *
 * <p>The other editor spec substitutes <see cref="EditorService"/> wholesale,
 * which answers every call synchronously. That is the right shape for testing
 * what the screen does with an answer, and the wrong one for testing whether
 * the screen ever gets it: a real poll is a request that takes a moment, over
 * an interval that keeps ticking, and both of those are exactly what the
 * mocked version removes. This file keeps the service and fakes only the
 * network under it — which is how the defect that got past the first set is
 * caught here.</p>
 */

const IMAGE = { width: 1200, height: 800, close: () => {} } as unknown as ImageBitmap;
const PROJECT = '0199a1f0-0000-7000-8000-000000000001';
const JOB = '0199a1f0-0000-7000-8000-00000000000a';

const RECIPE = {
  schema: 1,
  white_balance: { temperature: 0, tint: 0 },
  tone: { exposure: 0, contrast: 0, highlights: 0, shadows: 0, whites: 0, blacks: 0 },
  color: { saturation: 0, vibrance: 0 },
  tone_curve: {
    points: [
      [0, 0],
      [1, 1],
    ],
  },
};

function jobBody(status: string, error: string | null = null): Record<string, unknown> {
  return {
    id: JOB,
    status,
    createdAt: '2026-09-21T10:00:00+00:00',
    updatedAt: '2026-09-21T10:00:00+00:00',
    error,
    edit: RECIPE,
    result:
      status === 'done'
        ? {
            key: `${JOB}.png`,
            contentType: 'image/png',
            width: 6000,
            height: 4000,
            bytes: 29_652_571,
          }
        : null,
  };
}

describe('Editor · export over the real service', () => {
  let fixture: ComponentFixture<Editor>;
  let http: HttpTestingController;

  beforeEach(async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    vi.useFakeTimers();

    await TestBed.configureTestingModule({
      imports: [Editor],
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: (): string => PROJECT } } },
        },
        provideHttpClient(),
        provideHttpClientTesting(),
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
                versionCount: 0,
                hasChoice: true,
                startingEdit: RECIPE,
              }),
            proxy: (): Observable<ImageBitmap> => of(IMAGE),

            // Both answered empty: this file is about the export, and the two
            // calls the editor makes on open are not what is being tested.
            versions: (): Observable<readonly never[]> => of([]),
            exports: (): Observable<readonly never[]> => of([]),
          },
        },
        // The real one. Only the network underneath it is faked.
        EditorService,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Editor);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    // The history call the editor makes on open, answered so it is out of the
    // way of what this file is about.
    fixture.detectChanges();
  });

  afterEach(() => {
    vi.useRealTimers();
    http.match((request) => request.url.includes('/i18n/')).forEach((r) => r.flush({}));
    TestBed.resetTestingModule();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function press(label: string): void {
    const button = [...element().querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    );

    button!.click();
    fixture.detectChanges();
  }

  /** One poll: let the interval fire, then answer the request it made. */
  async function poll(status: string, error: string | null = null): Promise<void> {
    await vi.advanceTimersByTimeAsync(0);

    const request = http.expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`);
    request.flush(jobBody(status, error));

    fixture.detectChanges();
  }

  it('the view updates on its own, without anybody calling detectChanges', async () => {
    // The app is zoneless: nothing re-renders unless a signal write schedules
    // it. Every other test here calls detectChanges by hand, which is exactly
    // the step the browser does not have — so this one deliberately never
    // calls it, and fails if the screen would have sat there saying EXPORTING.
    press('editor.export');
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`).flush({ jobId: JOB });

    await vi.advanceTimersByTimeAsync(0);
    http.expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`).flush(jobBody('done'));

    await vi.advanceTimersByTimeAsync(0);
    await fixture.whenStable();

    expect(element().textContent).toContain('editor.download');
    expect(element().textContent).not.toContain('editor.exporting');
  });

  it('walks from asking to a finished file, and stops asking once it has one', async () => {
    press('editor.export');

    const queued = http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`);
    expect(queued.request.method).toBe('POST');
    queued.flush({ jobId: JOB });
    fixture.detectChanges();

    await poll('pending');
    expect(element().textContent).toContain('editor.exporting');

    await vi.advanceTimersByTimeAsync(1500);
    http.expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`).flush(jobBody('running'));
    fixture.detectChanges();
    expect(element().textContent).toContain('editor.exporting');

    await vi.advanceTimersByTimeAsync(1500);
    http.expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`).flush(jobBody('done'));
    fixture.detectChanges();

    // The whole point: the button has to change, and the asking has to stop.
    expect(element().textContent).toContain('editor.download');
    expect(element().textContent).not.toContain('editor.exporting');

    await vi.advanceTimersByTimeAsync(5000);
    http.expectNone(`${environment.apiBaseUrl}/jobs/${JOB}`);
  });

  it('a failure ends the waiting rather than leaving the button saying EXPORTING', async () => {
    press('editor.export');
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`).flush({ jobId: JOB });
    fixture.detectChanges();

    await poll('failed', 'the original this project was made from is no longer stored');

    expect(element().textContent).toContain('editor.exportFailed');
    expect(element().textContent).not.toContain('editor.exporting');
  });

  it('a poll that never answers is given up on rather than blocking the rest', async () => {
    // With exhaustMap a request in flight holds back the next tick, so one that
    // never answers would stop the screen learning anything ever again. The
    // timeout is what keeps that from being permanent.
    press('editor.export');
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`).flush({ jobId: JOB });
    fixture.detectChanges();

    await vi.advanceTimersByTimeAsync(0);
    http.expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`);

    // Nothing ever comes back for it. Past the timeout rather than exactly on
    // it, so the test does not depend on which side of the boundary the timer
    // lands.
    await vi.advanceTimersByTimeAsync(25_000);
    fixture.detectChanges();

    expect(element().textContent).not.toContain('editor.exporting');
    expect(element().textContent).toContain('errors.unexpected');
  });

  it('a wait that never reaches an answer has a floor under it', async () => {
    // The other shape of the same worry: every poll answers, and the answer is
    // always "still running". After five minutes the screen stops claiming to
    // be busy and offers another try; the job itself carries on regardless.
    press('editor.export');
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`).flush({ jobId: JOB });
    fixture.detectChanges();

    // Advanced synchronously and answered as it goes: two hundred polls that
    // each await the microtask queue is minutes of test time, and none of them
    // is what is being checked.
    for (let elapsed = 0; elapsed <= 5 * 60 * 1000; elapsed += 1500) {
      vi.advanceTimersByTime(elapsed === 0 ? 0 : 1500);
      http
        .match(`${environment.apiBaseUrl}/jobs/${JOB}`)
        .forEach((request) => request.flush(jobBody('running')));
    }

    fixture.detectChanges();

    expect(element().textContent).toContain('editor.exportSlow');
    expect(element().textContent).not.toContain('editor.exporting');
  });

  it('a poll slower than the interval is left to finish rather than cancelled', async () => {
    // The defect behind the hang: while the worker renders, a poll competes
    // with it for the machine and can take longer than the gap between polls.
    // With switchMap every tick aborted the request in flight, so the screen
    // could ask indefinitely and never once get an answer.
    press('editor.export');
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`).flush({ jobId: JOB });
    fixture.detectChanges();

    await vi.advanceTimersByTimeAsync(0);
    const slow = http.expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`);

    // Three intervals pass with that request still unanswered.
    await vi.advanceTimersByTimeAsync(4500);

    // No second request was started, and the first was not cancelled.
    http.expectNone(`${environment.apiBaseUrl}/jobs/${JOB}`);
    expect(slow.cancelled).toBe(false);

    slow.flush(jobBody('done'));
    await vi.advanceTimersByTimeAsync(0);
    fixture.detectChanges();

    expect(element().textContent).toContain('editor.download');
  });

  it('a poll that fails says so instead of waiting for ever', async () => {
    press('editor.export');
    http.expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}/export`).flush({ jobId: JOB });
    fixture.detectChanges();

    await vi.advanceTimersByTimeAsync(0);
    http
      .expectOne(`${environment.apiBaseUrl}/jobs/${JOB}`)
      .flush('nope', { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(element().textContent).toContain('errors.unexpected');
    expect(element().textContent).not.toContain('editor.exporting');
  });
});
