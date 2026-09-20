import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import {
  ActivatedRoute,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import { filter, map, startWith } from 'rxjs';

import { AuthService } from './core/auth/auth-service';

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
  imports: [RouterLink, RouterLinkActive, RouterOutlet, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);

  /**
   * Whether the header carries navigation at all.
   *
   * <p>Signed out, the only screens in the casing are the two forms, and each
   * already links to the other; a menu there would offer the screen you are
   * standing on. Signed in, the header is the one place every screen shares,
   * which is exactly why the way out has to live in it.</p>
   */
  protected readonly isAuthenticated = this.auth.isAuthenticated;

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

  /**
   * Drops the token and returns to the form.
   *
   * <p>Nothing is sent to the server: the token is a signed claim it keeps no
   * copy of, so signing out is a local act until revocation exists. The
   * navigation is what makes it visible — without it the guard would only
   * notice on the next attempt to go somewhere.</p>
   */
  protected signOut(): void {
    this.auth.signOut();
    void this.router.navigate(['/auth/login']);
  }

  private deepestZone(): Zone {
    let route = this.route;
    while (route.firstChild) {
      route = route.firstChild;
    }
    return route.snapshot.data['zone'] === 'display' ? 'display' : 'casing';
  }
}
