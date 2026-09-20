import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

import { ProjectsService } from '../projects-service';

/**
 * The photograph on a project card.
 *
 * <p><b>Why this is a component and not an `<img src>`.</b> The route serving
 * the picture needs the bearer token, and the interceptor only sees requests
 * made through HttpClient; an image element would fetch on its own and be
 * refused. The bytes therefore come back as a blob and become an object URL —
 * and an object URL is a reference the browser keeps until it is revoked, so it
 * needs an owner whose lifetime is exactly the picture's. That owner is this
 * component: when the card goes, the URL goes with it.</p>
 */
@Component({
  selector: 'app-project-thumbnail',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './project-thumbnail.html',
  styleUrl: './project-thumbnail.scss',
})
export class ProjectThumbnail implements OnDestroy {
  readonly photoId = input.required<string>();

  private readonly projects = inject(ProjectsService);

  protected readonly source = signal<string | null>(null);

  constructor() {
    effect(() => {
      const photoId = this.photoId();

      this.projects.thumbnail(photoId).subscribe({
        next: (blob) => this.replace(URL.createObjectURL(blob)),

        // A card without its picture is still a project that can be opened,
        // renamed and deleted. Taking the list down over one missing derivative
        // would lose the nine that arrived.
        error: () => this.replace(null),
      });
    });
  }

  ngOnDestroy(): void {
    this.replace(null);
  }

  /**
   * Swaps the address and releases the one it replaces.
   *
   * <p>Object URLs are the leak the phase warned about: nothing collects them,
   * because the browser cannot know the page has stopped referring to one. Every
   * path that drops a URL — a new photograph, a failure, the card going away —
   * goes through here, so there is one place to get it right instead of three.</p>
   */
  private replace(next: string | null): void {
    const previous = this.source();

    if (previous !== null) {
      URL.revokeObjectURL(previous);
    }

    this.source.set(next);
  }
}
