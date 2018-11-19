from os import system

import numpy as np
from helpers import *
from sympy import Matrix
from time import time


def normalize_rows(M):
    row_max = M.max(axis=1)
    return M / np.transpose(np.asarray(np.asmatrix(row_max, dtype='object'), dtype='object'))

def get_rownames(A):
    rownames = []
    for row_index in range(A.shape[0]):
        rownames.append([index for index, value in enumerate(A[row_index, :]) if value != 0])
    return rownames


def deflate_matrix(A, columns_to_keep):
    B = np.ndarray(shape=(0, len(columns_to_keep)), dtype=A.dtype)

    # Return rows that are nonzero after removing unwanted columns
    for row_index in range(A.shape[0]):
        row = A[row_index, columns_to_keep]
        if np.count_nonzero(row) > 0:
            B = np.append(B, [row], axis=0)

    return B


def inflate_matrix(A, kept_columns, original_width):
    B = np.zeros(shape=(A.shape[0], original_width), dtype=A.dtype)

    for index, col in enumerate(kept_columns):
        B[:, col] = A[:, index]

    return B


def redund(matrix, verbose=False):
    matrix = to_fractions(matrix)

    with open('tmp/matrix.ine', 'w') as file:
        file.write('H-representation\n')
        file.write('begin\n')
        file.write('%d %d rational\n' % (matrix.shape[0], matrix.shape[1] + 1))
        for row in range(matrix.shape[0]):
            file.write(' 0')
            for col in range(matrix.shape[1]):
                file.write(' %s' % str(matrix[row, col]))
            file.write('\n')
        file.write('end\n')

    system('scripts/redund tmp/matrix.ine > tmp/matrix_nored.ine')

    matrix_nored = np.ndarray(shape=(0, matrix.shape[1] + 1), dtype='object')

    with open('tmp/matrix_nored.ine') as file:
        lines = file.readlines()
        for line in [line for line in lines if line not in ['\n', '']]:
            # Skip comment and INE format lines
            if np.any([target in line for target in ['*', 'H-representation', 'begin', 'end', 'rational']]):
                continue
            row = [Fraction(x) for x in line.replace('\n', '').split(' ') if x != '']
            matrix_nored = np.append(matrix_nored, [row], axis=0)

    remove('tmp/matrix.ine')
    remove('tmp/matrix_nored.ine')

    if verbose:
        print('Removed %d redundant rows' % (matrix.shape[0] - matrix_nored.shape[0]))

    return matrix_nored[:, 1:]


def get_clementine_conversion_cone(N, external_metabolites=[], reversible_reactions=[], input_metabolites=[], output_metabolites=[],
                                   verbose=True):
    """
    Calculates the conversion cone using Superior Clementine Equality Intersection (all rights reserved).
    Follows the general Double Description method by Motzkin, using G as initial basis and intersecting
    hyperplanes of internal metabolites = 0.
    :param N:
    :param external_metabolites:
    :param reversible_reactions:
    :param input_metabolites:
    :param output_metabolites:
    :return:
    """
    amount_metabolites, amount_reactions = N.shape[0], N.shape[1]
    internal_metabolites = np.setdiff1d(range(amount_metabolites), external_metabolites)

    identity = np.identity(amount_metabolites)

    # Compose G of the columns of N
    G = np.transpose(N)

    # Add reversible reactions (columns) of N to G in the negative direction as well
    for reaction_index in range(G.shape[0]):
        if reaction_index in reversible_reactions:
            G = np.append(G, [-G[reaction_index, :]], axis=0)

    for index, internal_metabolite in enumerate(internal_metabolites):
        if verbose:
            print('Iteration %d/%d' % (index, len(internal_metabolites)))

        # Find conversions that use this metabolite
        active_conversions = np.asarray([conversion_index for conversion_index in range(G.shape[0])
                              if G[conversion_index, internal_metabolite] != 0])

        # Skip internal metabolites that aren't used anywhere
        if len(active_conversions) == 0:
            if verbose:
                print('Skipping internal metabolite #%d, since it is not used by any reaction\n' % internal_metabolite)
            continue

        # Project conversions that use this metabolite onto the hyperplane internal_metabolite = 0
        projections = np.dot(G[active_conversions, :], identity[:, internal_metabolite])
        positive = active_conversions[np.argwhere(projections > 0)[:, 0]]
        negative = active_conversions[np.argwhere(projections < 0)[:, 0]]
        candidates = np.ndarray(shape=(0, amount_metabolites))

        if verbose:
            print('Adding %d candidates' % (len(positive) * len(negative)))

        # Make convex combinations of all pairs (positive, negative) such that their internal_metabolite = 0
        for pos in positive:
            for neg in negative:
                candidate = np.add(G[pos, :], G[neg, :] * (G[pos, internal_metabolite] / -G[neg, internal_metabolite]))
                candidates = np.append(candidates, [candidate], axis=0)

        # Keep only rays that satisfy internal_metabolite = 0
        keep = np.setdiff1d(range(G.shape[0]), np.append(positive, negative, axis=0))
        if verbose:
            print('Removing %d rays\n' % (G.shape[0] - len(keep)))
        G = G[keep, :]
        G = np.append(G, candidates, axis=0)

    return G


def get_conversion_cone(N, tagged_rows=[], reversible_columns=[], input_metabolites=[], output_metabolites=[],
                        symbolic=True, verbose=False):
    """
    Calculates the conversion cone as described in (Urbanczik, 2005).
    :param N: stoichiometry matrix
    :param tagged_rows: list of row numbers (0-based) of metabolites that are tagged as in/outputs ("conversions")
    :param reversible_columns: list of booleans stating whether the reaction at this column is reversible
    :return: matrix with conversion cone "c" as row vectors
    """
    amount_metabolites, amount_reactions = N.shape[0], N.shape[1]

    # Compose G of the columns of N
    G = np.transpose(N)

    # Add reversible reactions (columns) of N to G in the negative direction as well
    for reaction_index in range(G.shape[0]):
        if reaction_index in reversible_columns:
            G = np.append(G, [-G[reaction_index, :]], axis=0)

    # TODO: remove debug block
    # G = redund(G)

    # Calculate H as the union of our linearities and the extreme rays of matrix G (all as row vectors)
    if verbose:
        print('Calculating extreme rays H of inequalities system G')

    # Calculate generating set of the dual of our initial conversion cone C0, C0*
    rays_full = get_extreme_rays_cdd(G)

    # Remove internal metabolites from the rays, since they are all equal to 0 in the conversion cone
    rays_deflated = deflate_matrix(rays_full, tagged_rows)

    # if verbose:
    #     print('Removing redundant rows from H')
    # rays_deflated = redund(rays_deflated)

    H_ineq = np.ndarray(shape=(0, rays_deflated.shape[1]))
    linearities = np.ndarray(shape=(0, rays_deflated.shape[1]))

    # Fill H_ineq with all generating rays that are not part of the nullspace (aka lineality space) of the dual cone C0*.
    # These represent the system of inequalities of our initial conversion cone C0.
    for row in range(rays_deflated.shape[0]):
        if np.all(np.dot(G, rays_full[row, :]) == 0):
            # This is a linearity
            linearities = np.append(linearities, [rays_deflated[row, :]], axis=0)
        else:
            # This is a normal extreme ray
            H_ineq = np.append(H_ineq, [rays_deflated[row, :]], axis=0)


    H_eq = linearities

    # Add input/output constraints to H_ineq
    if not H_ineq.shape[0]:
        H_ineq = np.zeros(shape=(1, H_ineq.shape[1]))

    identity = np.identity(H_ineq.shape[1])

    for input_metabolite in input_metabolites:
        index = tagged_rows.index(input_metabolite)
        H_ineq = np.append(H_ineq, [-identity[index, :]], axis=0)

    for output_metabolite in output_metabolites:
        index = tagged_rows.index(output_metabolite)
        H_ineq = np.append(H_ineq, [identity[index, :]], axis=0)

    # If there are inequalities, apply trick A3 from (Urbanczik, 2005, appendix)
    # make_homogeneous = H_ineq.shape[0] > 0
    make_homogeneous = False

    if verbose and make_homogeneous:
        print('Calculating nullspace A of H_eq')

    A = nullspace(H_eq, symbolic=symbolic) if make_homogeneous else None

    # Combine equality and inequality equations into homogenous inequality system
    # using Urbanczik A3.
    H_total = np.dot(H_ineq, A) if make_homogeneous else np.append(H_eq, -H_eq, axis=0)

    # Calculate the extreme rays of the cone C represented by inequalities H_total, resulting in
    # the elementary conversion modes of the input system.
    if verbose:
        print('Calculating extreme rays C of inequalities system H_total')

    # rays = np.asarray(list(get_extreme_rays_efmtool(H_total)))
    # rays = np.asarray(list(get_extreme_rays(None, H_total, verbose=True)))
    rays = np.asarray(list(get_extreme_rays(H_eq, H_ineq, verbose=True)))
    # rays = np.asarray(list(get_extreme_rays_cdd(H_total)))

    if rays.shape[0] == 0:
        print('Warning: no feasible Elementary Conversion Modes found')
        return rays

    if verbose:
        print('Extracting deflated rays')
    rays_deflated = np.transpose(np.dot(A, np.transpose(rays))) if make_homogeneous else rays

    if verbose:
        print('Inflating rays')
    rays_inflated = inflate_matrix(rays_deflated, tagged_rows, amount_metabolites)

    return rays_inflated


if __name__ == '__main__':
    start = time()

    S = np.asarray([
        [-1, 0, 0],
        [0, -1, 0],
        [1, 0, -1],
        [0, 1, -1],
        [0, 0, 1]])
    c = get_conversion_cone(S, [0, 1, 4], verbose=True)
    print(c)

    end = time()
    print('Ran in %f seconds' % (end - start))
    pass