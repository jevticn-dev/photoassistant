import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { environment } from '../../../environments/environment';
import { NEUTRAL_RECIPE, toDocument } from '../../renderer';
import { SuggestionsFailure, SuggestionsService } from './suggestions-service';

const PHOTO = '0199a1f0-0000-7000-8000-000000000002';
const PROJECT = '0199a1f0-0000-7000-8000-000000000001';

function offered(reference: string, exposure = 0) {
  // Built as a recipe and then serialised, rather than assembled as a loose
  // object: the document shape is the schema's business, and hand-writing it
  // here would let this test pass over a document the real one would refuse.
  const recipe = {
    ...NEUTRAL_RECIPE,
    tone: { ...NEUTRAL_RECIPE.tone, exposure },
  };

  return {
    recipe: toDocument(recipe),
    sourceReference: reference,
    expert: 'b',
    sceneDistance: 0.12,
  };
}

describe('SuggestionsService', () => {
  let service: SuggestionsService;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(SuggestionsService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('parses each recipe at the boundary rather than deeper in', () => {
    // parseRecipe is the schema's own validator, shared with the renderer. A
    // document it refuses must fail here, where the screen can say so, not
    // inside a shader.
    let parsed: readonly { recipe: { tone: { exposure: number } } }[] = [];
    service.suggestions(PHOTO).subscribe((value) => (parsed = value));

    http
      .expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/recommendations`)
      .flush({ suggestions: [offered('a0002', 0.35)], poolSize: 250 });

    expect(parsed[0].recipe.tone.exposure).toBe(0.35);
  });

  it('reports a recipe the editor could not apply as its own kind of failure', () => {
    // Distinguished from a network or server error: a document our own service
    // sent that the shared schema refuses is a defect on our side, and saying
    // "something went wrong" for it would lose that in the log.
    let failure: SuggestionsFailure | undefined;
    service
      .suggestions(PHOTO)
      .subscribe({ error: (error: SuggestionsFailure) => (failure = error) });

    http
      .expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/recommendations`)
      .flush({ suggestions: [{ ...offered('a0002'), recipe: { schema: 99 } }], poolSize: 250 });

    expect(failure?.summaryKey).toBe('suggestions.errors.unreadable');
  });

  it('asks for the proxy as a blob, so it can be decoded for the GPU', () => {
    service.proxy(PHOTO).subscribe({ error: () => undefined });

    const request = http.expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/proxy`);

    expect(request.request.responseType).toBe('blob');
    // Through HttpClient, so the interceptor attaches the token — a raw fetch
    // would need a second copy of where the token is kept.
    request.flush(new Blob([new Uint8Array([1, 2, 3])], { type: 'image/jpeg' }));
  });

  it('sends every suggestion that was shown, and which one was taken', () => {
    // The log is about what the person saw. Recording only the accepted edit
    // would lose the comparison it exists to support (plan §1.1).
    const shown = [offered('a0002'), offered('a0031'), offered('a0440')];
    service.recordChoice(PHOTO, shown, 1).subscribe();

    const request = http.expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/choices`);

    expect(request.request.body.shown).toHaveLength(3);
    expect(request.request.body.chosenIndex).toBe(1);
    request.flush(null);
  });

  it('records skipping as no choice rather than as a first choice', () => {
    service.recordChoice(PHOTO, [offered('a0002')], null).subscribe();

    const request = http.expectOne(`${environment.apiBaseUrl}/photos/${PHOTO}/choices`);

    expect(request.request.body.chosenIndex).toBeNull();
    request.flush(null);
  });

  it.each([
    [404, 'suggestions.errors.missing'],
    [401, 'suggestions.errors.signedOut'],
    [503, 'suggestions.errors.unavailable'],
    [500, 'suggestions.errors.unexpected'],
  ])('turns %i into its own message', (status, key) => {
    // 503 in particular: the ML service being down has to read as "try again"
    // rather than as "nothing was found for this photograph".
    let failure: SuggestionsFailure | undefined;
    service.project(PROJECT).subscribe({ error: (error: SuggestionsFailure) => (failure = error) });

    http
      .expectOne(`${environment.apiBaseUrl}/projects/${PROJECT}`)
      .flush({}, { status, statusText: '' });

    expect(failure?.summaryKey).toBe(key);
  });
});
