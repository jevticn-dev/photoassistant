import { ChangeDetectionStrategy, Component, OnDestroy, inject, signal } from '@angular/core';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { UploadFailure, UploadProgress, UploadService, fileError } from './upload-service';

/** What the browser will offer in the file picker, and what the API accepts. */
const ACCEPTED = 'image/jpeg,image/png,image/webp';

/**
 * Choosing a photograph, and watching it become a project.
 *
 * <p>The waiting state shows the photograph itself, dimmed, with a line
 * sweeping across it. The file is already in the browser — the person picked it
 * — so <code>createObjectURL</code> has it on screen before a single byte has
 * been sent, and it does not wait on the proxy the editor will later use.</p>
 *
 * <p>The sweep repeats rather than advancing, which says "working" and promises
 * nothing. It also happens to describe what is going on: the service is reading
 * that photograph. Only the sending phase has a real percentage, and only it
 * shows one (notes phase-4 §B94).</p>
 */
@Component({
  selector: 'app-upload',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './upload.html',
  styleUrl: './upload.scss',
})
export class Upload implements OnDestroy {
  private readonly uploads = inject(UploadService);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);

  protected readonly accepted = ACCEPTED;

  /**
   * What happens to a photograph after it is chosen.
   *
   * Listed here rather than written three times in the template: the numbering
   * and the key pattern are the kind of thing that drifts when duplicated, and
   * the strings still live in the translation file.
   */
  protected readonly steps = [
    { key: 'one', index: '01' },
    { key: 'two', index: '02' },
    { key: 'three', index: '03' },
  ].map((step) => ({
    ...step,
    label: `upload.steps.${step.key}.label`,
    text: `upload.steps.${step.key}.text`,
  }));

  protected readonly progress = signal<UploadProgress | null>(null);
  protected readonly failure = signal<UploadFailure | null>(null);
  protected readonly dragging = signal(false);

  /** The chosen file, shown while the upload runs. */
  protected readonly preview = signal<SafeUrl | null>(null);

  /** Held separately from the SafeUrl, which cannot be revoked. */
  private objectUrl: string | null = null;

  protected readonly message = (): string | null => fileError(this.failure());

  ngOnDestroy(): void {
    this.releasePreview();
  }

  protected onDragOver(event: DragEvent): void {
    // Without preventDefault the browser navigates to the dropped file, which
    // looks like the application crashing.
    event.preventDefault();
    this.dragging.set(true);
  }

  protected onDragLeave(): void {
    this.dragging.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);

    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.start(file);
    }
  }

  protected onPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];

    if (file) {
      this.start(file);
    }

    // Cleared so that picking the same file twice in a row still fires a
    // change event; a browser reports no change otherwise.
    input.value = '';
  }

  protected percent(): number {
    const progress = this.progress();

    return progress?.phase === 'sending' ? progress.percent : 0;
  }

  protected phase(): 'idle' | 'sending' | 'processing' {
    const progress = this.progress();

    if (progress === null || progress.phase === 'done') {
      return 'idle';
    }

    return progress.phase;
  }

  private start(file: File): void {
    if (this.phase() !== 'idle') {
      return;
    }

    this.failure.set(null);
    this.showPreview(file);

    // Indeterminate to begin with, for the same reason the service treats
    // `Sent` that way: nothing is known about how much has gone out, and a
    // zero would be a claim rather than an absence.
    this.progress.set({ phase: 'processing' });

    this.uploads.upload(file).subscribe({
      next: (progress) => {
        this.progress.set(progress);

        if (progress.phase === 'done') {
          // Straight into the project. The suggestion screen is what the person
          // came for; an interstitial saying "uploaded" would be a click to
          // dismiss a fact they can already see.
          void this.router.navigate(['/projects', progress.photo.projectId]);
        }
      },
      error: (failure: UploadFailure) => {
        this.failure.set(failure);
        this.progress.set(null);
        this.releasePreview();
      },
    });
  }

  private showPreview(file: File): void {
    this.releasePreview();

    try {
      this.objectUrl = URL.createObjectURL(file);
      // Angular blocks a blob: URL in [src] as unsafe unless it is told the
      // origin is ours, which it is: the person picked this file.
      this.preview.set(this.sanitizer.bypassSecurityTrustUrl(this.objectUrl));
    } catch {
      // A format the browser cannot decode — HEIC from a phone, or a RAW file.
      // The upload still proceeds; only the backdrop is missing.
      this.preview.set(null);
    }
  }

  private releasePreview(): void {
    if (this.objectUrl !== null) {
      // Every object URL holds its file in memory until revoked, and an upload
      // screen is somewhere a person lands repeatedly.
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }

    this.preview.set(null);
  }
}
