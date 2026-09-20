import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { vi } from 'vitest';

import { provideTranslations } from '../../core/i18n/translation.config';
import { PhotoApi, type Project } from '../../shared/photos/photo-api';
import { Editor } from './editor';
import { EditorService, type SavedVersion, type VersionEntry } from './editor-service';

/**
 * A stand-in for the decoded working copy. Nothing in these tests draws — jsdom
 * has no WebGL2 — so only the two dimensions and a close that does nothing are
 * ever reached.
 */
const IMAGE = { width: 1200, height: 800, close: () => {} } as unknown as ImageBitmap;

const PROJECT = '0199a1f0-0000-7000-8000-000000000001';

/** Recorded so a test can see what was actually sent to be stored. */
let saved: unknown;

/** How many times this screen has saved, so each one earns the next label. */
let saves: number;

function project(startingEdit: unknown, versionCount = 0): Project {
  return {
    id: PROJECT,
    name: 'Alpine Ridge',
    photoId: '0199a1f0-0000-7000-8000-000000000002',
    createdAt: '2026-09-20T10:00:00+00:00',
    versionCount,
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

/** A recipe told apart from the others by one value. */
function recipeWith(contrast: number): unknown {
  return { ...CHOSEN, tone: { ...CHOSEN.tone, contrast } };
}

/**
 * A history of `count` versions, the newest of which is what the project opens
 * on — which is what the server guarantees (§B110) and what the strip has to
 * agree with.
 */
function historyOf(count: number, newest: unknown): VersionEntry[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `version-${index + 1}`,
    label: `V${String(index + 1).padStart(2, '0')}`,
    createdAt: '2026-09-20T10:00:00+00:00',
    edit: index === count - 1 ? newest : recipeWith((index + 1) * 10),
  }));
}

describe('Editor', () => {
  let fixture: ComponentFixture<Editor>;
  let http: HttpTestingController;

  beforeEach(() => {
    saved = undefined;
    saves = 0;

    // jsdom has no canvas of any kind, and asking it for a context prints a
    // page of "not implemented" for every test. Answering null is what a
    // browser without WebGL2 does anyway, so the screen is exercised along the
    // path it has to survive rather than one jsdom invented.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  async function open(
    startingEdit: unknown = CHOSEN,
    versionCount = 0,
    historyFails = false,
  ): Promise<void> {
    const history = historyOf(versionCount, startingEdit);

    await TestBed.configureTestingModule({
      imports: [Editor],
      providers: [
        provideRouter([]),
        {
          // The editor is addressed by project id, and reads it from the route
          // rather than being handed it. Without this the screen loads but the
          // save button has nothing to save into.
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: (): string => PROJECT } } },
        },
        provideHttpClient(),
        provideHttpClientTesting(),
        provideTranslations(),
        {
          // The screen is about what happens to a recipe once it is on screen,
          // so both calls answer at once and neither is what is being tested.
          provide: PhotoApi,
          useValue: {
            project: (): Observable<Project> => of(project(startingEdit, versionCount)),
            proxy: (): Observable<ImageBitmap> => of(IMAGE),
          },
        },
        {
          provide: EditorService,
          useValue: {
            versions: (): Observable<readonly VersionEntry[]> =>
              historyFails ? throwError(() => ({ summaryKey: 'errors.unreachable' })) : of(history),
            saveVersion: (_: string, recipe: unknown): Observable<SavedVersion> => {
              saved = recipe;
              saves += 1;

              // The label the server would give it: the next position in this
              // project's history, which is what makes a restore land as the
              // newest version rather than replacing the one it came from.
              return of({
                id: `saved-${saves}`,
                label: `V${String(history.length + saves).padStart(2, '0')}`,
                createdAt: '2026-09-20T10:00:00+00:00',
              });
            },
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

  function chips(): HTMLButtonElement[] {
    return [...element().querySelectorAll<HTMLButtonElement>('.chip')];
  }

  function openVersion(label: string): void {
    chips()
      .find((chip) => chip.textContent?.trim() === label)!
      .click();
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

  it('opens saying nothing has been saved, and says so until something is', async () => {
    await open();

    expect(element().textContent).toContain('editor.unsaved');
  });

  it('saving names the version, and the bar stops asking', async () => {
    await open(null);

    drag('contrast', 20);
    press('editor.save');

    expect(element().textContent).toContain('editor.saved');
    expect(element().textContent).not.toContain('editor.changed');
  });

  it('editing after a save says so again', async () => {
    // The one state worth colouring: the other two are steady, this one is
    // asking for something.
    await open(null);

    press('editor.save');
    drag('shadows', 15);

    expect(element().textContent).toContain('editor.changed');
  });

  it('a project that already has versions opens as saved', async () => {
    // The editor opens on the newest version when there is one (§B110), so
    // that is also what "saved" means the moment the screen appears.
    await open(CHOSEN, 3);

    expect(element().textContent).toContain('editor.saved');
  });

  it('what is sent is the recipe itself, in the schema form', async () => {
    await open(null);

    drag('exposure', 0.5);
    press('editor.save');

    expect(saved).toMatchObject({ schema: 1, tone: { exposure: 0.5 } });
  });

  // -- the history ------------------------------------------------------------

  it('the strip shows every saved version, oldest first', async () => {
    // Oldest first because the labels are positions: V01 is the first thing
    // saved and stays V01, so reading downwards is reading forwards in time.
    await open(CHOSEN, 3);

    expect(chips().map((chip) => chip.textContent?.trim())).toEqual(['V01', 'V02', 'V03']);
  });

  it('a project with nothing saved has a strip with nothing in it', async () => {
    // An abandoned upload is an ordinary state (decision G). The strip says so
    // rather than disappearing, which would move the photograph on first save.
    await open(null);

    expect(chips()).toHaveLength(0);
    expect(element().textContent).toContain('editor.history.empty');
  });

  it('opening an earlier version puts it on screen and writes nothing', async () => {
    await open(CHOSEN, 3);

    openVersion('V01');

    expect(valueOf('contrast')).toBe(10);
    expect(saved).toBeUndefined();
    expect(chips()).toHaveLength(3);
  });

  it('the work in progress is one undo away after opening a version', async () => {
    // Deliberately instead of a dialog asking whether unsaved work may be
    // discarded: the strip is meant to be clicked through, and the work is not
    // lost — it is one step behind.
    await open(CHOSEN, 3);

    drag('contrast', 55);
    openVersion('V01');
    expect(valueOf('contrast')).toBe(10);

    press('editor.undo');
    expect(valueOf('contrast')).toBe(55);
  });

  it('the bar says which version is being looked at', async () => {
    // An earlier version on screen looks exactly like work somebody is in the
    // middle of, so it has to be said out loud.
    await open(CHOSEN, 3);

    openVersion('V01');

    expect(element().textContent).toContain('editor.viewing');
    expect(element().textContent).toContain('editor.restore');
  });

  it('restoring appends the old recipe and keeps everything newer', async () => {
    // The point of the whole task: history only grows, so going back to V01 is
    // saving it again (§B118). Nothing newer is touched.
    await open(CHOSEN, 3);

    openVersion('V01');
    press('editor.restore');

    expect(saved).toMatchObject({ tone: { contrast: 10 } });
    expect(chips().map((chip) => chip.textContent?.trim())).toEqual(['V01', 'V02', 'V03', 'V04']);
    expect(element().textContent).toContain('editor.saved');
  });

  it('the newest version is not something to restore, because it is already there', async () => {
    await open(CHOSEN, 3);

    openVersion('V03');

    expect(element().textContent).toContain('editor.saved');
    expect(element().textContent).not.toContain('editor.restore');
  });

  it('a history that could not be read says so, rather than looking empty', async () => {
    // An empty strip because the request failed looks exactly like an empty
    // strip because nothing has been saved.
    await open(CHOSEN, 0, true);

    expect(element().textContent).toContain('editor.history.failed');
  });
});
