import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Observable, of } from 'rxjs';
import { vi } from 'vitest';

import { provideTranslations } from '../../core/i18n/translation.config';
import { PhotoApi, type Project } from '../../shared/photos/photo-api';
import { Editor } from './editor';

/**
 * A stand-in for the decoded working copy. Nothing in these tests draws — jsdom
 * has no WebGL2 — so only the two dimensions and a close that does nothing are
 * ever reached.
 */
const IMAGE = { width: 1200, height: 800, close: () => {} } as unknown as ImageBitmap;

function project(startingEdit: unknown): Project {
  return {
    id: '0199a1f0-0000-7000-8000-000000000001',
    name: 'Alpine Ridge',
    photoId: '0199a1f0-0000-7000-8000-000000000002',
    createdAt: '2026-09-20T10:00:00+00:00',
    versionCount: 0,
    hasChoice: true,
    startingEdit,
  };
}

const CHOSEN = {
  schema: 1,
  white_balance: { temperature: 14, tint: 0 },
  tone: { exposure: 0.35, contrast: 18, highlights: 0, shadows: 24, whites: 0, blacks: 0 },
  color: { saturation: 0, vibrance: 8 },
  tone_curve: {
    points: [
      [0, 0],
      [1, 1],
    ],
  },
};

describe('Editor', () => {
  let fixture: ComponentFixture<Editor>;
  let http: HttpTestingController;

  beforeEach(() => {
    // jsdom has no canvas of any kind, and asking it for a context prints a
    // page of "not implemented" for every test. Answering null is what a
    // browser without WebGL2 does anyway, so the screen is exercised along the
    // path it has to survive rather than one jsdom invented.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  async function open(startingEdit: unknown = CHOSEN): Promise<void> {
    await TestBed.configureTestingModule({
      imports: [Editor],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideTranslations(),
        {
          // The screen is about what happens to a recipe once it is on screen,
          // so both calls answer at once and neither is what is being tested.
          provide: PhotoApi,
          useValue: {
            project: (): Observable<Project> => of(project(startingEdit)),
            proxy: (): Observable<ImageBitmap> => of(IMAGE),
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Editor);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  }

  afterEach(() => {
    // ngx-translate fetches its catalogue through the same testing backend.
    http?.match((request) => request.url.includes('/i18n/')).forEach((r) => r.flush({}));
    http?.verify();
    TestBed.resetTestingModule();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function slider(key: string): HTMLInputElement {
    return element().querySelector<HTMLInputElement>(`#param-${key}`)!;
  }

  function valueOf(key: string): number {
    return Number(slider(key).value);
  }

  /** One gesture: the pointer goes down, values arrive, the pointer comes up. */
  function drag(key: string, ...values: number[]): void {
    const track = slider(key);

    track.dispatchEvent(new Event('pointerdown'));

    for (const value of values) {
      track.value = String(value);
      track.dispatchEvent(new Event('input'));
    }

    track.dispatchEvent(new Event('pointerup'));
    fixture.detectChanges();
  }

  function press(label: string): void {
    const button = [...element().querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    );

    button!.click();
    fixture.detectChanges();
  }

  it('opens on the recipe the server hands over', async () => {
    // Carried from the server rather than from the previous screen, so that
    // reloading the editor — the ordinary way back into a project — lands in
    // the same place rather than on the untouched photograph.
    await open();

    expect(valueOf('temperature')).toBe(14);
    expect(valueOf('exposure')).toBe(0.35);
    expect(valueOf('vibrance')).toBe(8);
  });

  it('opens on the photograph unchanged when there is nothing to open on', async () => {
    await open(null);

    expect(valueOf('temperature')).toBe(0);
    expect(valueOf('exposure')).toBe(0);
  });

  it('opens on the photograph unchanged when the document is not a recipe', async () => {
    // The API passes the document on without reading it, and the column it came
    // from only promises that it is JSON (§B107). Refusing to open would be a
    // worse answer than opening on a photograph with every control in reach.
    await open({ nonsense: true });

    expect(valueOf('contrast')).toBe(0);
    expect(element().querySelector('#param-contrast')).not.toBeNull();
  });

  it('every scalar parameter of the schema has a control', async () => {
    await open(null);

    expect(element().querySelectorAll('input[type="range"]')).toHaveLength(10);
  });

  it('a drag is one step, however many values it emits', async () => {
    // A slider emits a value per pixel of travel. An entry each would turn undo
    // into a slow rewind of a movement nobody remembers making.
    await open(null);

    drag('contrast', 5, 10, 15, 20, 25);
    expect(valueOf('contrast')).toBe(25);

    press('editor.undo');
    expect(valueOf('contrast')).toBe(0);
  });

  it('redo puts back what undo took, and editing drops it', async () => {
    await open(null);

    drag('shadows', 30);
    press('editor.undo');
    press('editor.redo');
    expect(valueOf('shadows')).toBe(30);

    press('editor.undo');
    drag('whites', 12);

    // Redo led back into work that no longer follows from here.
    const redo = [...element().querySelectorAll('button')].find(
      (button) => button.textContent?.trim() === 'editor.redo',
    );
    expect(redo!.disabled).toBe(true);
  });

  it('undo and redo are unavailable when there is nothing to undo', async () => {
    await open(null);

    const buttons = [...element().querySelectorAll('button')];
    const undo = buttons.find((button) => button.textContent?.trim() === 'editor.undo');

    expect(undo!.disabled).toBe(true);
  });

  it('resetting a parameter is a step of its own', async () => {
    await open();

    const reset = element()
      .querySelector<HTMLButtonElement>('#param-temperature')!
      .closest('.param')!
      .querySelector<HTMLButtonElement>('.param__value')!;

    reset.click();
    fixture.detectChanges();
    expect(valueOf('temperature')).toBe(0);

    press('editor.undo');
    expect(valueOf('temperature')).toBe(14);
  });

  it('the keyboard undoes as well, without reaching for the toolbar', async () => {
    await open(null);

    drag('blacks', 20);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }));
    fixture.detectChanges();

    expect(valueOf('blacks')).toBe(0);
  });

  it('the comparison is off until it is asked for', async () => {
    await open();

    expect(element().querySelector('[role="slider"]')).toBeNull();

    press('editor.compare');
    expect(element().querySelector('[role="slider"]')).not.toBeNull();
  });

  it('the divider answers the keys a slider answers to, and stays in the frame', async () => {
    await open();
    press('editor.compare');

    const divider = element().querySelector('[role="slider"]')!;

    divider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
    fixture.detectChanges();
    expect(divider.getAttribute('aria-valuenow')).toBe('45');

    divider.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home' }));
    fixture.detectChanges();
    expect(divider.getAttribute('aria-valuenow')).toBe('0');

    divider.dispatchEvent(new KeyboardEvent('keydown', { key: 'End' }));
    fixture.detectChanges();
    expect(divider.getAttribute('aria-valuenow')).toBe('100');
  });

  it('says so when the browser cannot draw the preview', async () => {
    // A black rectangle with no explanation is the failure this replaces: a
    // missing WebGL2 produces no console error of its own (decision I).
    await open();

    expect(element().textContent).toContain('editor.unsupported');
  });

  it('offers a way back, since the shell hides its own in this zone', async () => {
    // Found by reloading into the editor: the display zone has no application
    // header, so without this the only way out of the screen is the browser's
    // own Back — and after a fresh sign-in there is no history to go back to.
    await open();

    const home = element().querySelector<HTMLAnchorElement>('.bar__home');

    expect(home?.getAttribute('href')).toBe('/projects');
  });

  it('says that nothing is being saved, rather than letting it be assumed', async () => {
    // Saving is task 6. A screen that looks like an editor is taken to keep
    // what is done in it unless it says otherwise.
    await open();

    expect(element().textContent).toContain('editor.unsaved');
  });
});
