import { HttpClient, HttpErrorResponse, HttpEventType } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, filter, map, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';

/** What the API returns once the photograph is stored and a project opened. */
export interface UploadedPhoto {
  readonly projectId: string;
  readonly photoId: string;
  readonly name: string;
  readonly width: number;
  readonly height: number;
}

/**
 * Where an upload has got to.
 *
 * Two states rather than a single percentage, because the wait has two parts
 * that behave differently. Sending has a real fraction — bytes acknowledged out
 * of bytes to send. Everything after it, the derive and the three writes to
 * storage, reports nothing at all: the request is simply open. Presenting the
 * second as a number would be inventing one (notes phase-4 §B94).
 */
export type UploadProgress =
  | { readonly phase: 'sending'; readonly percent: number }
  | { readonly phase: 'processing' }
  | { readonly phase: 'done'; readonly photo: UploadedPhoto };

export interface UploadFailure {
  /** Field-keyed messages from the API, as ValidationProblemDetails. */
  readonly fields: Readonly<Record<string, readonly string[]>>;
  /** A translation key for a message of our own. */
  readonly summaryKey: string | null;
}

interface ValidationProblem {
  readonly errors?: Record<string, string[]>;
}

/**
 * The ceiling, matching `UploadPhotoHandler.MaximumBytes` on the server.
 *
 * Duplicated deliberately, and the duplication is the lesser evil. The server
 * enforces it because it must; the browser checks it because of how exceeding
 * it actually fails: Kestrel drops the connection while the body is still going
 * out, so the browser reports a network error rather than a 413. The person
 * then reads "check your connection" about a file that is simply too big.
 */
export const MAXIMUM_BYTES = 40 * 1024 * 1024;

/** What the server will decode. Mirrors the handler's allowlist. */
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

/**
 * What is wrong with this file, before any of it is sent.
 *
 * Only the two things a browser can know for certain. Whether the bytes are
 * really an image is the ML service's verdict, and a renamed file still has to
 * travel to get it.
 */
export function rejectionFor(file: File): UploadFailure | null {
  if (file.size === 0) {
    return { fields: {}, summaryKey: 'upload.errors.empty' };
  }

  if (file.size > MAXIMUM_BYTES) {
    return { fields: {}, summaryKey: 'upload.errors.tooLarge' };
  }

  if (!ACCEPTED_TYPES.includes(file.type.toLowerCase())) {
    // Drag and drop ignores the input's `accept`, so this is reachable.
    return { fields: {}, summaryKey: 'upload.errors.wrongType' };
  }

  return null;
}

@Injectable({ providedIn: 'root' })
export class UploadService {
  private readonly http = inject(HttpClient);

  /**
   * Sends one photograph and reports progress until the project exists.
   *
   * `reportProgress` is what makes the sending fraction available at all;
   * without it the observable emits once, at the end, and the bar would jump
   * from nothing to everything.
   */
  upload(file: File): Observable<UploadProgress> {
    // Short-circuited here rather than in the screen, so no caller can forget
    // and send 45 MB at a server that will drop the connection mid-body.
    const rejection = rejectionFor(file);
    if (rejection !== null) {
      return throwError(() => rejection);
    }

    const body = new FormData();
    // The field name matches the controller's parameter. A mismatch binds null
    // and the request fails as a validation error nobody can explain.
    body.append('file', file, file.name);

    return this.http
      .post<UploadedPhoto>(`${environment.apiBaseUrl}/photos`, body, {
        observe: 'events',
        reportProgress: true,
      })
      .pipe(
        map((event): UploadProgress | null => {
          // `Sent` means the request was dispatched, not that the body is out —
          // Angular emits it immediately after `xhr.send()`. Reading it as "0%
          // uploaded" was wrong in the case that matters most: over a fast link
          // the body leaves in one write and no useful UploadProgress follows,
          // so the status froze at 0% for the whole server-side wait.
          //
          // So the default is `processing`, and a percentage appears only while
          // a measured upload is genuinely in flight. The trade is deliberate:
          // on a slow connection the first instant reads as processing before
          // the first progress event corrects it, which is briefly imprecise;
          // the alternative was a number that is wrong for seconds.
          if (event.type === HttpEventType.Sent) {
            return { phase: 'processing' };
          }

          if (event.type === HttpEventType.UploadProgress) {
            // No total means no fraction to show; work is still happening.
            if (!event.total) {
              return { phase: 'processing' };
            }

            // Once the final byte is out the wait belongs to the server. A bar
            // held at 100% would say finished while the slow part runs.
            return event.loaded >= event.total
              ? { phase: 'processing' }
              : { phase: 'sending', percent: Math.round((event.loaded / event.total) * 100) };
          }

          if (event.type === HttpEventType.ResponseHeader) {
            return { phase: 'processing' };
          }

          if (event.type === HttpEventType.Response && event.body) {
            return { phase: 'done', photo: event.body };
          }

          return null;
        }),
        // The events we do not model — headers received, download progress on
        // a response of a few hundred bytes — carry nothing a person can see.
        filter((progress): progress is UploadProgress => progress !== null),
        catchError((error: unknown) => throwError(() => toFailure(error))),
      );
  }
}

function toFailure(error: unknown): UploadFailure {
  if (!(error instanceof HttpErrorResponse)) {
    return { fields: {}, summaryKey: 'upload.errors.unexpected' };
  }

  if (error.status === 400) {
    const problem = error.error as ValidationProblem | null;
    const fields = problem?.errors ?? {};

    return {
      fields: Object.fromEntries(
        Object.entries(fields).map(([field, messages]) => [field.toLowerCase(), messages]),
      ),
      summaryKey: Object.keys(fields).length > 0 ? null : 'upload.errors.unexpected',
    };
  }

  if (error.status === 401) {
    return { fields: {}, summaryKey: 'upload.errors.signedOut' };
  }

  // 413 is the server's size limit rather than ours: the request never reached
  // the handler, so there is no field-keyed message to show.
  if (error.status === 413) {
    return { fields: {}, summaryKey: 'upload.errors.tooLarge' };
  }

  return {
    fields: {},
    summaryKey: error.status === 0 ? 'upload.errors.unreachable' : 'upload.errors.unexpected',
  };
}

/** The first message about the file itself, if the API sent one. */
export function fileError(failure: UploadFailure | null): string | null {
  return failure?.fields['file']?.[0] ?? null;
}
