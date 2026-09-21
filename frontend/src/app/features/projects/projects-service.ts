import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { toApiFailure } from '../../shared/photos/photo-api';

export type { ApiFailure as ProjectsFailure } from '../../shared/photos/photo-api';

/** One project as the list shows it — no recipe, because a list shows none. */
export interface ProjectListItem {
  readonly id: string;
  readonly name: string;
  readonly photoId: string;
  readonly versionCount: number;
  readonly lastEditedAt: string;
}

@Injectable({ providedIn: 'root' })
export class ProjectsService {
  private readonly http = inject(HttpClient);

  list(): Observable<readonly ProjectListItem[]> {
    return this.http
      .get<readonly ProjectListItem[]>(`${environment.apiBaseUrl}/projects`)
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  rename(projectId: string, name: string): Observable<{ readonly name: string }> {
    return this.http
      .patch<{ readonly name: string }>(`${environment.apiBaseUrl}/projects/${projectId}`, {
        name,
      })
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  delete(projectId: string): Observable<void> {
    return this.http
      .delete<void>(`${environment.apiBaseUrl}/projects/${projectId}`)
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }

  /**
   * The 512px copy, as bytes rather than as an address.
   *
   * <p>An `<img src>` cannot be used directly: the route needs the bearer
   * token, and the interceptor only sees requests that go through HttpClient —
   * a plain image element would arrive unauthenticated and answer 401. So the
   * bytes are fetched here and the caller turns them into an object URL, which
   * it then has to revoke. That obligation is why fetching lives beside a
   * component whose lifetime matches the image's.</p>
   */
  thumbnail(photoId: string): Observable<Blob> {
    return this.http
      .get(`${environment.apiBaseUrl}/photos/${photoId}/thumbnail`, { responseType: 'blob' })
      .pipe(catchError((error: unknown) => throwError(() => toApiFailure(error))));
  }
}
