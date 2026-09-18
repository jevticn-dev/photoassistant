import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import { filter, map, startWith } from 'rxjs';

/** Which surface a screen is drawn on. See styles/_tokens.scss. */
export type Zone = 'casing' | 'display';

/**
 * Application shell. Holds only what surrounds every screen; each area lives in
 * its own lazily loaded feature under features/.
 *
 * It also decides the **zone**: light casing for everything that carries
 * controls, dark display for any screen showing a photograph under edit. A
 * route declares its own with `data: { zone: 'display' }` and the class lands on
 * the wrapper, which is where the tokens are redefined. Casing is the default,
 * so only the editor has to say anything.
 *
 * The zone is read from the route rather than from the URL, so that moving or
 * renaming a route cannot silently change how it looks.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /**
   * The deepest activated route's zone, recomputed on every navigation.
   *
   * `startWith` matters: NavigationEnd has already fired for the first screen by
   * the time this subscribes, so without it the application would render its
   * first route with no zone at all.
   */
  private readonly zone = toSignal(
    this.router.events.pipe(
      filter((event) => event instanceof NavigationEnd),
      startWith(null),
      map(() => this.deepestZone()),
    ),
    { initialValue: 'casing' as Zone },
  );

  protected readonly zoneClass = computed(() => `zone-${this.zone()}`);

  /** True while a screen draws its own surface and the shell chrome is in the way. */
  protected readonly isDisplay = computed(() => this.zone() === 'display');

  private deepestZone(): Zone {
    let route = this.route;
    while (route.firstChild) {
      route = route.firstChild;
    }
    return route.snapshot.data['zone'] === 'display' ? 'display' : 'casing';
  }
}
