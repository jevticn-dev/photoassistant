import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import { Subscription, timer } from 'rxjs';
import { exhaustMap, takeUntil, takeWhile } from 'rxjs/operators';

import {
  type CurvePoint,
  EditSchemaError,
  NEUTRAL_RECIPE,
  type EditRecipe,
  parseRecipe,
  toDocument,
  toJson,
} from '../../renderer';
import {
  PhotoApi,
  type ApiFailure,
  type JobState,
  type Project,
  type VersionEntry,
  saveBlob,
} from '../../shared/photos/photo-api';
import { CurveEditor } from './curve-editor';
import { EditorCanvas, type CanvasFailure } from './editor-canvas';
import { EditorService } from './editor-service';
import { type ParamDef, SECTIONS, readParam, writeParam } from './editor-params';
import { ParamSlider } from './param-slider';
import { type StripEntry, VersionStrip } from './version-strip';

/**
 * How many edits back undo reaches.
 *
 * <p>An entry is a whole recipe, about a kilobyte, so fifty is a rounding error
 * in memory. The limit exists because an unbounded stack has no failure mode
 * anyone notices until it has one.</p>
 */
const HISTORY_LIMIT = 50;

/** Below this the working copy is not worth degrading any further (decision I). */
const SMALLEST_WORKING_COPY = 512;

/** How far an arrow key moves the comparison divider, in percent. */
const DIVIDER_STEP = 5;

/**
 * How often to ask how the export is coming along.
 *
 * <p>A full-resolution render is seconds of work — six at 24 megapixels,
 * measured — so a second and a half is the right order: often enough that the
 * finish is not noticeably late, rare enough that a long export is a handful of
 * requests rather than a stream of them.</p>
 */
const EXPORT_POLL_MS = 1500;

/**
 * How long to keep asking before giving up on an export.
 *
 * <p>Generously past anything measured — the slowest render in the corpus is
 * twelve seconds — because this is not a deadline for the work but a floor
 * under the screen: after this the button stops claiming to be busy and offers
 * to try again. The export itself is a row in a table and carries on
 * regardless; what ends here is only the waiting.</p>
 */
const EXPORT_GIVE_UP_MS = 5 * 60 * 1000;

/** The two states that mean the work has not finished one way or the other. */
function inProgress(job: JobState): boolean {
  return job.status === 'pending' || job.status === 'running';
}

/**
 * The editor: one photograph, every scalar parameter of edit schema v1, and the
 * result redrawn as each one moves.
 *
 * <p><b>Nothing goes to the server while editing.</b> The renderer the corpus
 * was fitted with runs in the browser over the 2048px working copy, so moving a
 * slider costs a draw rather than a network round trip. That is ADR-3, and the
 * reason the schema exists as a document at all.</p>
 *
 * <p>Saving is explicit, and so is the history beside it: each save is a whole
 * recipe (ADR-6), and going back to one appends it again rather than undoing
 * what came after. The bar always says which of the four states the work is in,
 * because an editor that looks like it keeps your work and does not is worse
 * than one that admits it.</p>
 */
@Component({
  selector: 'app-editor',
  imports: [CurveEditor, EditorCanvas, ParamSlider, RouterLink, TranslatePipe, VersionStrip],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './editor.html',
  styleUrl: './editor.scss',
  host: {
    // Undo and redo where the hands already are. Bound on the document rather
    // than on the host, so they work before anything has been focused — which
    // is the state the screen opens in.
    '(document:keydown)': 'onShortcut($event)',
  },
})
export class Editor implements OnDestroy {
  private readonly api = inject(PhotoApi);
  private readonly editor = inject(EditorService);
  private readonly route = inject(ActivatedRoute);

  private readonly projectId = this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly sections = SECTIONS;

  /** The photograph as it was uploaded — what "before" means here. */
  protected readonly neutral = NEUTRAL_RECIPE;

  protected readonly project = signal<Project | null>(null);
  protected readonly image = signal<ImageBitmap | null>(null);
  protected readonly recipe = signal<EditRecipe>(NEUTRAL_RECIPE);
  protected readonly failure = signal<ApiFailure | null>(null);

  /** Set once the working copy has had to be made smaller, and never unset. */
  protected readonly degraded = signal(false);
  protected readonly unsupported = signal(false);

  /**
   * The recipe as it was last saved, in canonical form, or null when nothing
   * has been saved for this project.
   *
   * <p>Kept as text rather than as a recipe because what is being asked is
   * "has anything changed", and two recipes are equal when their canonical
   * documents are — which is the same comparison the agreement test makes
   * across the three languages.</p>
   */
  private readonly savedEdit = signal<string | null>(null);

  protected readonly savedLabel = signal<string | null>(null);
  protected readonly saving = signal(false);

  /** Set when a save failed, and cleared by the next attempt. */
  protected readonly saveProblem = signal<string | null>(null);

  /**
   * Everything saved for this project, oldest first — the strip down the side.
   *
   * <p>Each entry brings its recipe with it, so opening one is a redraw rather
   * than a request (§B117).</p>
   */
  protected readonly versions = signal<readonly VersionEntry[]>([]);

  /** Set when the history could not be read, so an empty strip is not read as "nothing saved". */
  protected readonly historyProblem = signal<string | null>(null);

  /**
   * The version that was opened, and the document it put on screen.
   *
   * <p>Both halves, because the second is what keeps the first honest. Editing
   * after opening V01 means V01 is no longer what is being looked at, and a
   * flag alone would have to be cleared from every path that changes the
   * recipe — a slider, a reset, undo, redo, a save. Holding the document
   * instead makes the question answerable rather than remembered.</p>
   */
  private readonly opened = signal<{ id: string; document: string } | null>(null);

  /** Which chip is lit: the opened version, but only while it is still what is shown. */
  protected readonly openId = computed(() => {
    const open = this.opened();

    return open !== null && toJson(this.recipe()) === open.document ? open.id : null;
  });

  /**
   * The version the save button would put back on top, or null when saving
   * means what it usually means.
   *
   * <p>The newest version is not restorable: it is already on top, and the bar
   * beside the button says so. Only looking further back turns a save into a
   * restore.</p>
   */
  protected readonly restorable = computed(() => {
    const id = this.openId();
    const list = this.versions();

    if (id === null || list.length === 0 || list[list.length - 1].id === id) {
      return null;
    }

    return list.find((version) => version.id === id) ?? null;
  });

  /**
   * The export being waited on, or null when none is.
   *
   * <p>One at a time: the button is disabled while this is set, because two
   * exports of the same photograph differ only in which finished last, and the
   * second would tell the person nothing the first will not.</p>
   */
  protected readonly job = signal<JobState | null>(null);

  /** Set while the request to queue one is in flight, before there is a job. */
  protected readonly requestingExport = signal(false);

  /** Set when the export could not be asked for, or its file not fetched. */
  protected readonly exportProblem = signal<string | null>(null);

  /** True from the moment the button is pressed until there is a file or a failure. */
  protected readonly exporting = computed(() => {
    const job = this.job();

    return this.requestingExport() || job?.status === 'pending' || job?.status === 'running';
  });

  /**
   * A finished export found when the screen opened, rather than watched here.
   *
   * <p>Kept apart from <c>job</c> on purpose: the two mean different things to
   * the screen. This one says a file exists; that one says something is
   * happening now. Mixing them would announce "your photograph is ready" every
   * time a project with an old export is opened.</p>
   */
  private readonly previousExport = signal<JobState | null>(null);

  /** The export that just finished here — what the notice announces. */
  protected readonly exported = computed(() => {
    const job = this.job();

    return job?.status === 'done' ? job : null;
  });

  /**
   * A finished export of **this** picture — what the button offers.
   *
   * <p>The comparison is the point. A file that was rendered before the last
   * slider moved is no longer the photograph on screen, and a button still
   * saying DOWNLOAD would hand over a different picture than the one being
   * looked at. Recipes rather than versions, because an export is not tied to a
   * version (§B118) and an unsaved change is still a change the file does not
   * have.</p>
   *
   * <p>Canonical documents on both sides, the same equality `dirty` and the
   * version strip use: two recipes are the same when their canonical JSON
   * is.</p>
   */
  protected readonly downloadable = computed(() => {
    const job = this.exported() ?? this.previousExport();

    if (job === null) {
      return null;
    }

    const rendered = readRecipe(job.edit);

    // A document that will not parse cannot be shown to match anything. It
    // came from our own queue, so this is a defect rather than a condition —
    // and offering the file anyway would be guessing on the person's behalf.
    return rendered !== null && toJson(rendered) === toJson(this.recipe()) ? job : null;
  });

  protected readonly comparing = signal(false);
  protected readonly divider = signal(50);

  /** On a narrow screen the panel is a drawer, and this is whether it is up. */
  protected readonly controlsOpen = signal(false);

  private readonly past = signal<readonly EditRecipe[]>([]);
  private readonly future = signal<readonly EditRecipe[]>([]);

  protected readonly canUndo = computed(() => this.past().length > 0);
  protected readonly canRedo = computed(() => this.future().length > 0);

  /** True once there is something to look at; the screen shows nothing before. */
  protected readonly ready = computed(() => this.image() !== null);

  /** True when the edit differs from the last thing saved. */
  protected readonly dirty = computed(() => {
    const saved = this.savedEdit();

    return saved !== null && toJson(this.recipe()) !== saved;
  });

  /**
   * What the bar says about the work: never saved, saved and untouched since,
   * changed since, or looking at an earlier version. Four states rather than
   * two, because each is a different thing to be told — and the last one has to
   * be said out loud, since an older version on screen looks exactly like work
   * somebody is in the middle of.
   */
  protected readonly status = computed(() => {
    if (this.restorable() !== null) {
      return 'editor.viewing';
    }

    if (this.savedLabel() === null) {
      return 'editor.unsaved';
    }

    return this.dirty() ? 'editor.changed' : 'editor.saved';
  });

  /** Which label the status line and the save button name. */
  protected readonly statusLabel = computed(() => this.restorable()?.label ?? this.savedLabel());

  /**
   * What clips the edited layer. `none` while the split is off, so the whole
   * photograph shows the edit and the second canvas does not exist at all.
   */
  protected readonly clip = computed(() =>
    this.comparing() ? `inset(0 0 0 ${this.divider()}%)` : 'none',
  );

  /** The divider as a whole number, which is what aria-valuenow must be. */
  protected readonly dividerPosition = computed(() => Math.round(this.divider()));

  private readonly frame = viewChild<ElementRef<HTMLElement>>('frame');

  private stepOpen = false;
  private dragging = false;
  private degrading = false;
  private polling: Subscription | null = null;

  constructor() {
    this.load();
  }

  ngOnDestroy(): void {
    // Decoded pixels: 2048 x 1365 x 4 is eleven megabytes, held until the
    // bitmap is closed or collected. Closing it is cheap and certain.
    this.image()?.close();

    // Leaving the screen stops the asking. The export itself carries on — it
    // belongs to the job queue, not to this component — and is waiting when the
    // project is opened again.
    this.polling?.unsubscribe();
  }

  // -- the photograph -------------------------------------------------------

  /**
   * The frame carries the photograph's own ratio, so both layers fill exactly
   * the same box. Without it the divider's percentage would be measured against
   * a frame wider than the photograph inside it, and the seam would sit beside
   * the edit rather than on it.
   */
  protected aspectRatio(image: ImageBitmap): string {
    return `${image.width} / ${image.height}`;
  }

  /**
   * The GPU could not do it. Which of two answers this gets depends on whether
   * anything is left to try.
   *
   * <p>A missing WebGL2 is final and is said plainly. Running out of graphics
   * memory is not: it arrives as a lost context with nothing in the console,
   * and halving the working copy is the one thing that helps (decision I). The
   * person is told, because a preview that quietly changed resolution is a
   * difference they would otherwise discover while judging sharpness.</p>
   */
  protected onCanvasFailure(failure: CanvasFailure): void {
    if (failure === 'no-webgl2') {
      this.unsupported.set(true);

      return;
    }

    const current = this.image();
    if (current === null || this.degrading) {
      return;
    }

    const longest = Math.max(current.width, current.height);
    if (longest <= SMALLEST_WORKING_COPY) {
      return;
    }

    this.degrading = true;

    // Half, but never below the floor: 2048 becomes 1024, which is where plan
    // §11 wanted to start and decision I moved to here, where it is a response
    // to the failure that actually happens rather than a guess ahead of it.
    const scale = Math.max(SMALLEST_WORKING_COPY / longest, 0.5);

    void createImageBitmap(current, {
      resizeWidth: Math.round(current.width * scale),
      resizeHeight: Math.round(current.height * scale),
      resizeQuality: 'high',

      // The same two switches as the original decode: the renderer agrees with
      // the Python side only for pixels nothing has transformed on the way in.
      premultiplyAlpha: 'none',
      colorSpaceConversion: 'none',
    })
      .then((smaller) => {
        current.close();
        this.image.set(smaller);
        this.degraded.set(true);
      })
      .finally(() => {
        this.degrading = false;
      });
  }

  // -- the parameters -------------------------------------------------------

  protected value(param: ParamDef): number {
    return readParam(this.recipe(), param);
  }

  protected setValue(param: ParamDef, value: number): void {
    this.recipe.update((recipe) => writeParam(recipe, param, value));
  }

  /**
   * The curve's control points, as the editor holds them.
   *
   * <p>Through the recipe rather than beside it: the curve is one of the
   * thirteen parameters, saved with the rest and rendered with the rest. A
   * separate piece of state for it would be a second place where "the edit"
   * lives.</p>
   */
  protected setCurve(points: readonly CurvePoint[]): void {
    this.recipe.update((recipe) => ({ ...recipe, toneCurve: { points } }));
  }

  protected reset(param: ParamDef): void {
    if (this.value(param) === 0) {
      return;
    }

    this.beginStep();
    this.recipe.update((recipe) => writeParam(recipe, param, 0));
    this.endStep();
  }

  // -- history --------------------------------------------------------------

  /**
   * One gesture is one step.
   *
   * <p>A drag across the track emits hundreds of values, and an entry per value
   * would turn undo into a slow rewind of a movement nobody remembers making.
   * The snapshot is taken when a gesture starts — a pointer going down, a key
   * going down — and the gesture stays open until it ends. Holding an arrow key
   * repeats without releasing it, so a long press is still one step.</p>
   */
  protected beginStep(): void {
    if (this.stepOpen) {
      return;
    }

    this.stepOpen = true;
    this.past.update((list) => [...list.slice(-(HISTORY_LIMIT - 1)), this.recipe()]);

    // Redo is what was undone, and editing after an undo is a different branch.
    // Keeping the old future would offer a step forward into work that no
    // longer follows from here.
    this.future.set([]);
  }

  protected endStep(): void {
    this.stepOpen = false;
  }

  protected undo(): void {
    const past = this.past();
    if (past.length === 0) {
      return;
    }

    this.future.update((list) => [...list, this.recipe()]);
    this.past.set(past.slice(0, -1));
    this.recipe.set(past[past.length - 1]);
  }

  protected redo(): void {
    const future = this.future();
    if (future.length === 0) {
      return;
    }

    this.past.update((list) => [...list, this.recipe()]);
    this.future.set(future.slice(0, -1));
    this.recipe.set(future[future.length - 1]);
  }

  protected onShortcut(event: KeyboardEvent): void {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') {
      return;
    }

    event.preventDefault();

    if (event.shiftKey) {
      this.redo();
    } else {
      this.undo();
    }
  }

  // -- history --------------------------------------------------------------

  /**
   * Puts an earlier version on screen.
   *
   * <p><b>As an ordinary undo step, not a mode.</b> Whatever was being worked
   * on goes onto the undo stack on the way past, so Ctrl+Z comes straight back
   * to it. That is deliberately instead of a dialog asking whether unsaved work
   * may be discarded: the strip is meant to be clicked through, and a modal on
   * every chip would make comparing two versions cost two confirmations. The
   * work is not lost, it is one step behind.</p>
   *
   * <p>Nothing is written. Looking at V01 leaves the history exactly as it
   * was — what writes is the save button, which while this is showing offers to
   * put V01 back on top as a new version (§B118).</p>
   */
  protected openVersion(entry: StripEntry): void {
    const version = this.versions().find((candidate) => candidate.id === entry.id);
    if (version === undefined) {
      return;
    }

    const recipe = readRecipe(version.edit);
    if (recipe === null) {
      // Stored, so it passed validation once; unreadable now means the schema
      // has moved under it. Said plainly rather than opening something that is
      // not what the chip promises.
      this.historyProblem.set('errors.unreadable');

      return;
    }

    this.historyProblem.set(null);

    this.beginStep();
    this.recipe.set(recipe);
    this.endStep();

    this.opened.set({ id: version.id, document: toJson(recipe) });
  }

  // -- saving ---------------------------------------------------------------

  /**
   * Writes the edit as a version.
   *
   * <p>Explicit rather than automatic, and that is the decision rather than the
   * easy way out: `edit_versions` rows are versions, and the schema has no
   * notion of a draft. Saving on every change would make the history a list of
   * a hundred entries per sitting instead of the handful of turning points
   * somebody meant to keep (§B111).</p>
   *
   * <p><b>This is also how a version is restored.</b> When what is on screen is
   * an earlier version, saving appends its recipe as the newest one — which is
   * the only thing "go back to V01" can mean where history only ever grows.
   * Nothing is rewritten and nothing newer is lost, and that holds because of
   * the shape rather than because of a rule (§B118).</p>
   */
  protected save(): void {
    if (this.saving() || this.projectId === '') {
      return;
    }

    const recipe = this.recipe();

    this.saving.set(true);
    this.saveProblem.set(null);

    this.editor.saveVersion(this.projectId, recipe).subscribe({
      next: (version) => {
        // The recipe as it was when the request went out, not as it is now:
        // moving a slider while the save is in flight must leave the screen
        // saying there are unsaved changes, because there are.
        const document = toJson(recipe);

        this.savedEdit.set(document);
        this.savedLabel.set(version.label);

        // Appended rather than refetched: the server was just told exactly this
        // recipe, and it answered with the label it gave it. Asking for the
        // list again would be a round trip to learn what is already known.
        this.versions.update((list) => [...list, { ...version, edit: toDocument(recipe) }]);

        // The new version is what is on screen now, so the strip lights it —
        // including after a restore, where the chip that lights is the new one
        // rather than the old one it came from.
        this.opened.set({ id: version.id, document });
        this.saving.set(false);
      },
      error: (failure: ApiFailure) => {
        this.saveProblem.set(failure.summaryKey);
        this.saving.set(false);
      },
    });
  }

  // -- export ---------------------------------------------------------------

  /**
   * Asks for the photograph at full size, with the edit as it stands.
   *
   * <p><b>What is exported is what is on screen</b>, not the newest saved
   * version, and asking does not save one: a version is a turning point
   * somebody meant to keep and an export is not (§B111). The two are
   * deliberately unlinked, so exporting a trial edit leaves no trace in the
   * history.</p>
   *
   * <p>Nothing renders here. The recipe goes to the queue, the ML service takes
   * it, and this screen asks how it is going — a full-resolution render is
   * seconds of arithmetic over hundreds of megabytes (ADR-7, §B121).</p>
   */
  protected requestExport(): void {
    if (this.exporting() || this.projectId === '') {
      return;
    }

    this.requestingExport.set(true);
    this.exportProblem.set(null);
    this.job.set(null);

    // Whatever was there before is no longer what the button means; the one
    // being asked for now is.
    this.previousExport.set(null);

    this.editor.requestExport(this.projectId, this.recipe()).subscribe({
      next: ({ jobId }) => {
        this.requestingExport.set(false);
        this.follow(jobId);
      },
      error: (failure: ApiFailure) => {
        this.exportProblem.set(failure.summaryKey);
        this.requestingExport.set(false);
      },
    });
  }

  /**
   * Asks after the job until it stops being in progress.
   *
   * <p>Polling rather than a push, because the queue is a table and nothing
   * pushes from it (ADR-7). The subscription is held so that leaving the screen
   * stops the asking.</p>
   */
  private follow(jobId: string): void {
    this.polling?.unsubscribe();

    this.polling = timer(0, EXPORT_POLL_MS)
      .pipe(
        // `exhaustMap`, not `switchMap`, and the difference is the defect it
        // fixes rather than a preference. switchMap cancels whatever is in
        // flight when the next tick arrives — and a poll competes for the
        // machine with the very render it is asking about, so under load every
        // request can be aborted a moment before it would have answered. The
        // screen then asks for ever and learns nothing; in the browser's
        // network panel that is a column of cancelled requests
        // (NS_BINDING_ABORTED in Firefox), which is what put us on to it.
        //
        // exhaustMap ignores a tick while a request is still running, so every
        // request gets to finish and the interval becomes a floor on the gap
        // between polls rather than a deadline for them.
        //
        // A request that never answers would block every tick after it, so the
        // service puts a timeout on the call itself.
        exhaustMap(() => this.editor.job(jobId)),

        // The stream ends itself once the answer is terminal, and `true` keeps
        // that last answer rather than swallowing it.
        //
        // This is deliberately an operator rather than an unsubscribe inside
        // `next`, and that is the fix rather than a tidy-up: a handler that
        // both stores the state and ends the subscription can, if anything in
        // it throws, end the subscription without storing the state — and RxJS
        // sends a throw from `next` nowhere near the `error` branch. The screen
        // is then left saying EXPORTING for ever, with no message and no way
        // out. Below, `next` does one thing that cannot fail.
        takeWhile(inProgress, true),

        // A floor under the waiting. Whatever else happens — a poll that never
        // answers, a worker that never gets to the job — the button stops
        // claiming to be busy.
        takeUntil(timer(EXPORT_GIVE_UP_MS)),
      )
      .subscribe({
        next: (job) => this.job.set(job),
        error: (failure: ApiFailure) => {
          this.exportProblem.set(failure.summaryKey);
          this.job.set(null);
          this.polling = null;
        },
        complete: () => {
          this.polling = null;

          // Completing while the job is still in progress means the deadline
          // above ran out, not that the work finished. Said plainly, and the
          // state is cleared so the button offers to try again rather than
          // sitting on a stale "running".
          const job = this.job();

          if (job !== null && inProgress(job)) {
            this.exportProblem.set('editor.exportSlow');
            this.job.set(null);
          }
        },
      });
  }

  /**
   * Hands the finished file to the browser.
   *
   * <p>Fetched rather than linked to, because the address needs the bearer
   * token the interceptor attaches and an anchor carries none. The object URL
   * is revoked once the click has been dispatched — the browser has the blob by
   * then, and leaving it would hold the whole export in memory for as long as
   * the page is open.</p>
   */
  protected download(): void {
    const job = this.downloadable();
    if (job === null) {
      return;
    }

    this.exportProblem.set(null);

    this.api.download(job.id).subscribe({
      next: (blob) => saveBlob(blob, `${this.project()?.name ?? 'photograph'}.png`),
      error: (failure: ApiFailure) => this.exportProblem.set(failure.summaryKey),
    });
  }

  // -- before and after -----------------------------------------------------

  /**
   * Comparison is a mode, not the resting state.
   *
   * <p>The prototype draws the divider down the middle of the photograph, which
   * is what the feature looks like. Leaving it parked there would mean every
   * adjustment is judged on half an image, so the editor opens showing the edit
   * whole and the split is asked for. It is also what keeps a phone usable,
   * where half of a small photograph is very little to go on.</p>
   */
  protected toggleCompare(): void {
    this.comparing.update((on) => !on);
    this.divider.set(50);
  }

  protected startDividerDrag(event: PointerEvent): void {
    event.preventDefault();
    (event.target as Element).setPointerCapture(event.pointerId);
    this.dragging = true;
  }

  protected moveDivider(event: PointerEvent): void {
    const frame = this.frame()?.nativeElement;
    if (!this.dragging || frame === undefined) {
      return;
    }

    const box = frame.getBoundingClientRect();
    this.divider.set(clamp(((event.clientX - box.left) / box.width) * 100));
  }

  protected endDividerDrag(event: PointerEvent): void {
    (event.target as Element).releasePointerCapture(event.pointerId);
    this.dragging = false;
  }

  /** The divider is a slider, so it answers the keys a slider answers to. */
  protected onDividerKey(event: KeyboardEvent): void {
    const move: Record<string, number> = {
      ArrowLeft: -DIVIDER_STEP,
      ArrowRight: DIVIDER_STEP,
      Home: -100,
      End: 100,
    };

    const step = move[event.key];
    if (step === undefined) {
      return;
    }

    event.preventDefault();
    this.divider.update((position) => clamp(position + step));
  }

  // -- loading --------------------------------------------------------------

  protected retry(): void {
    this.failure.set(null);
    this.load();
  }

  /**
   * The project first, because the working copy is addressed by the photograph
   * it names — and because the recipe to open on comes with it. Reading both
   * from the server rather than carrying them from the previous screen is what
   * makes the editor survive a reload, which is the ordinary way back into a
   * project.
   */
  private load(): void {
    this.api.project(this.projectId).subscribe({
      next: (project) => {
        this.project.set(project);

        const starting = startingRecipe(project);
        this.recipe.set(starting);

        // A project with versions opens on the newest of them, so that is also
        // what "saved" means here; one with none opens on a suggestion or on
        // nothing, and neither has been saved.
        if (project.versionCount > 0) {
          this.savedEdit.set(toJson(starting));
          this.savedLabel.set(`V${String(project.versionCount).padStart(2, '0')}`);
        }

        this.api.proxy(project.photoId).subscribe({
          next: (image) => this.image.set(image),
          error: (failure: ApiFailure) => this.failure.set(failure),
        });

        // A file rendered earlier is still a file. Asked for quietly: if this
        // fails the editor is no worse off than before, so it says nothing.
        this.api.exports(this.projectId).subscribe({
          next: (exports) => {
            const newest = exports[0];

            if (newest !== undefined && newest.status === 'done') {
              this.previousExport.set(newest);
            }
          },
          error: () => undefined,
        });

        // The history is read beside the photograph rather than before it: an
        // editor without its strip still edits, so a failure here is a notice
        // and not a screen that will not open.
        this.api.versions(this.projectId).subscribe({
          next: (versions) => {
            this.versions.set(versions);

            // Which chip the project opened on. The editor starts from the
            // newest saved version (§B110), so lighting it is stating a fact
            // rather than making a choice — and it is what tells the person
            // that the strip and the photograph are the same thing.
            const newest = versions[versions.length - 1];

            if (newest !== undefined && project.versionCount > 0) {
              this.opened.set({ id: newest.id, document: toJson(this.recipe()) });
            }
          },
          error: (failure: ApiFailure) => this.historyProblem.set(failure.summaryKey),
        });
      },
      error: (failure: ApiFailure) => this.failure.set(failure),
    });
  }
}

/**
 * Where the editing starts: what the server says, or the photograph unchanged.
 *
 * <p>The document is validated here rather than trusted, because the API passes
 * it on without reading it — the client owns the model of the schema, and the
 * column it came from guarantees only that it is JSON (§B107). A document that
 * is not a recipe opens neutral rather than refusing to open: the photograph
 * and every control are still there, which is a far better place to be than a
 * screen that will not load.</p>
 */
function startingRecipe(project: Project): EditRecipe {
  if (project.startingEdit === null || project.startingEdit === undefined) {
    return NEUTRAL_RECIPE;
  }

  return readRecipe(project.startingEdit) ?? NEUTRAL_RECIPE;
}

/**
 * A stored document as a recipe, or null when it is not one.
 *
 * <p>Null rather than a throw, because both callers have somewhere better to
 * go than an error: the screen opens neutral, and the strip says the entry
 * could not be read. A failure that is not the schema's is still thrown —
 * that one is a defect rather than a document.</p>
 */
function readRecipe(document: unknown): EditRecipe | null {
  try {
    return parseRecipe(document);
  } catch (error) {
    if (error instanceof EditSchemaError) {
      return null;
    }

    throw error;
  }
}

function clamp(percent: number): number {
  return Math.min(100, Math.max(0, percent));
}
